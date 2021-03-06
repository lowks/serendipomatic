import re

from fabric import api as fab
from fabric import colors
from fabric.api import env, task
from fabric.context_managers import cd, hide, settings
from fabric.contrib import files

import smartstash

'''
Setup required to use this fabric deploy:

* This path is assumed to be top level directory for deploy
  (this will contain deployed code which be linked as current/previous):
  /var/www/serendipomatic/

* Also assumes a user 'serendip' that owns the deployed code; users running
  the fab deploy should have sudo access to the serendip account.

* Create localsettings.py in the top-level deploy dir; this file should by
  the serendip user.

* Create a local-reqs.txt file in top-level deploy dir, should contain
  (or whatever python module is required for the database in use):
  MySQL-python

* Configure apache to use the current deploy symlink
  /var/www/serendipomatic/current for all paths

* Create backup/restore db scripts as documented below.

* Make sure the log file configured in django settings is readable and
  writable by both apache and serendip (e.g. via a web group)

'''

##
# deploy tasks
##

env.project = 'smartstash'
# NOTE: would like to use serendip, but fab deploy currently uses for appname
# TODO: refactor/rename django app from smartstash to serendip
env.rev_tag = ''
env.git_rev = ''
env.remote_path = '/var/www/serendipomatic/'
env.remote_acct = 'serendip'
env.webgroup = 'webwrite'

def configure():
    'Configuration settings used internally for the build.'

    env.version = smartstash.__version__
    config_from_git()
    # construct a unique build directory name based on software version and git revision
    env.build_dir = '%(project)s-%(version)s%(rev_tag)s' % env
    env.tarball = '%(project)s-%(version)s%(git_rev)s.tar.bz2' % env


def config_from_git():
    """Infer revision from local git checkout."""
    # if not a released version, use revision tag
    env.git_rev = fab.local('git rev-parse --short HEAD', capture=True).strip()
    if smartstash.__version_info__[-1]:
        env.rev_tag = '-r' + env.git_rev

def prep_source():
    'Checkout the code from git and do local prep.'

    fab.require('git_rev', 'build_dir',
            used_for='Exporting code from git into build area')

    fab.local('mkdir -p build')
    fab.local('rm -rf build/%(build_dir)s' % env)
    # create a tar archive of the specified version and extract inside the bulid directory
    fab.local('git archive --format=tar --prefix=%(build_dir)s/ %(git_rev)s | (cd build && tar xf -)' % env)

    # local settings handled on remote server


def package_source():
    'Create a tarball of the source tree.'
    fab.local('mkdir -p dist')
    fab.local('tar cjf dist/%(tarball)s -C build %(build_dir)s' % env)


def upload_source():
    'Copy the source tarball to the target server.'
    fab.put('dist/%(tarball)s' % env,
            '/tmp/%(tarball)s' % env)


def extract_source():
    'Extract the remote source tarball under the configured remote directory.'
    with cd(env.remote_path):
        fab.sudo('tar xjf /tmp/%(tarball)s' % env, user=env.remote_acct)
        # if the untar succeeded, remove the tarball
        fab.run('rm /tmp/%(tarball)s' % env)
        # update apache.conf if necessary


def setup_virtualenv():
    '''Create a virtualenv and install required packages on the remote server.

    If a local-reqs.txt file exists at the level above (e.g., for server-specific
    requirements, like python mysql, those will also be installed).

    '''

    with cd('%(remote_path)s/%(build_dir)s' % env):
        # create the virtualenv under the build dir
        # require python 2.7 even if not system default
        fab.sudo('virtualenv --no-site-packages --prompt=\'[%(build_dir)s]\' --python=/usr/bin/python2.7 env' \
                 % env, user=env.remote_acct)
        # activate the environment and install required packages
        with fab.prefix('source env/bin/activate'):
            fab.sudo('pip install -r requirements.txt', user=env.remote_acct)
            if files.exists('../local-reqs.txt'):
                fab.sudo('pip install -r ../local-reqs.txt', user=env.remote_acct)


def configure_site():
    '''Copy configuration file (localsettings) into the remote source tree,
    collect static files, and make them world-readable.
    '''
    with cd(env.remote_path):
        if not files.exists('localsettings.py'):
            fab.abort('Configuration file is not in expected location: %(remote_path)s/localsettings.py' % env)
        fab.sudo('cp localsettings.py %(build_dir)s/%(project)s/localsettings.py' % env,
                 user=env.remote_acct)

    with cd('%(remote_path)s/%(build_dir)s' % env):
        with fab.prefix('source env/bin/activate'):
            fab.sudo('python manage.py collectstatic --noinput' % env,
                     user=env.remote_acct)
            # make static files world-readable
            fab.sudo('chmod -R a+r `env DJANGO_SETTINGS_MODULE=\'%(project)s.settings\' python -c \'from django.conf import settings; print settings.STATIC_ROOT\'`' % env,
                 user=env.remote_acct)

    # make sure permissions are ok for apache
    with cd(env.remote_path):
        fab.sudo('chgrp -R %(webgroup)s %(build_dir)s' % env,
                 user=env.remote_acct)

def update_links():
    'Update current/previous symlinks on the remote server.'
    with fab.cd(env.remote_path):
        if files.exists('current' % env):
            current_target = fab.sudo('readlink current', user=env.remote_acct)
            # if current link points to the version currently being deployed
            # (i.e., on a re-deploy of same version), do nothing
            if current_target == env.build_dir:
                return

            fab.sudo('rm -f previous; mv current previous', user=env.remote_acct)
        fab.sudo('ln -sf %(build_dir)s current' % env, user=env.remote_acct)


@task   # FIXME: possibly not a separate task but part of main deploy, since it will be fully-automated
def syncdb():
    '''Remotely run syncdb and migrate after deploy and configuration.'''
    with fab.cd('%(remote_path)s/%(build_dir)s' % env):
        with fab.prefix('source env/bin/activate'):
            fab.sudo('python manage.py syncdb --noinput' % env,
                     user=env.remote_acct)
            # enable this if we ever start using south for db migrations
            # fab.sudo('python manage.py migrate --noinput' % env,
            #          user=env.remote_acct)

def backup_db():
    # create a script like this in /home/serendip/bin/backup_db with credentials,
    # should only be readable by serendip user (chmod 700)
    # (also create db_backup folder)
    # mysqldump -u smartstash --password=#### smartstash | gzip > /home/serendip/db_backup/smartstash.sql.gz
    fab.sudo('/home/serendip/bin/backup_db', user=env.remote_acct)


def restore_db():
    # create a script like this in /home/serendip/bin/restore_db with credentials,
    # should only be readable by serendip user (chmod 700)
    # gunzip < /home/serendip/db_backup/smartstash.sql.gz | mysql -u smartstash --password=#### smartstash
    fab.sudo('/home/serendip/bin/restore_db', user=env.remote_acct)

def restart_apache():
    fab.sudo('service httpd restart')


@task
def build_source_package(path=None, user=None):
    '''Produce a tarball of the source tree.'''
    configure(path=path, user=user)
    prep_source()
    package_source()


@task
def deploy():
    '''Deploy the web app to a remote server.

    Usage:
      fab deploy -H servername

    '''
    # prepare deploy
    configure()
    prep_source()
    package_source()
    # upload and set up on the server
    upload_source()
    extract_source()
    setup_virtualenv()
    configure_site()
    update_links()
    compare_localsettings()
    # database: backup in case we need to restore, sync any django model changes
    backup_db()
    syncdb()
    # restart apache
    restart_apache()
    # clean up
    rm_old_builds()


@task
def revert():
    """Update remote symlinks and database to retore the previous version as current"""
    configure()
    # if there is a previous link, shift current to previous
    with cd(env.remote_path):
        if files.exists('previous'):
            # remove the current link (but not actually removing code)
            fab.sudo('rm current', user=env.remote_acct)

            # make previous link current
            fab.sudo('mv previous current', user=env.remote_acct)
            fab.sudo('readlink current', user=env.remote_acct)

    # restore the last database backup & restart apache
    restore_db()
    restart_apache()


@task
def clean():
    '''Remove build/dist artifacts generated by deploy task'''
    fab.local('rm -rf build dist')
    # should we do any remote cleaning?


@task
def compare_localsettings(path=None, user=None):
    'Compare current/previous (if any) localsettings on the remote server.'
    configure()
    with cd(env.remote_path):
        # sanity-check current localsettings against previous
        if files.exists('previous'):
            with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                          warn_only=True):  # suppress output, don't abort on diff error exit code
                output = fab.sudo('diff current/%(project)s/localsettings.py previous/%(project)s/localsettings.py' % env,
                                  user=env.remote_acct)
                if output:
                    fab.puts(colors.yellow('WARNING: found differences between current and previous localsettings.py'))
                    fab.puts(output)
                else:
                    fab.puts(colors.green('No differences between current and previous localsettings.py'))


def identify_build_dirs():
    # generate a list of deployed build directories
    with cd(env.remote_path):
        with hide('stdout'):  # suppress ls/readlink output
            # get directory listing sorted by modification time (single-column for splitting)
            dir_listing = fab.sudo('ls -t1', user=env.remote_acct)

    # split dir listing on newlines and strip whitespace
    dir_items = [n.strip() for n in dir_listing.split('\n')]
    # regex based on how we generate the build directory:
    #   project name, numeric version, optional pre/dev suffix, optional revision #
    build_dir_regex = r'^%(project)s-[0-9.]+(-[A-Za-z0-9_-]+)?(-r[0-9]+)?$' % env
    return [item for item in dir_items if re.match(build_dir_regex, item)]


@task
def rm_old_builds():
    '''Remove old build directories on the deploy server.  Keeps the
    three most recent deploy directories, and does not remove current
    or previous linked deploys.
    '''
    configure()
    with cd(env.remote_path):
        with hide('stdout'):  # suppress readlink output
            # get current and previous links so we don't remove either of them
            current = fab.sudo('readlink current', user=env.remote_acct) if files.exists('current') else None
            previous = fab.sudo('readlink previous', user=env.remote_acct) if files.exists('previous') else None

        build_dirs = identify_build_dirs()
        # by default, preserve the 3 most recent build dirs from deletion
        rm_dirs = build_dirs[3:]
        # if current or previous for some reason is not in the 3 most recent,
        # make sure we don't delete it
        for link in [current, previous]:
            if link in rm_dirs:
                rm_dirs.remove(link)

        if rm_dirs:
            for dir in rm_dirs:
                fab.sudo('rm -rf %s' % dir, user=env.remote_acct)
        else:
            fab.puts('No old build directories to remove')
