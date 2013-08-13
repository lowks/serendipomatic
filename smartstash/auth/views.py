from django.http import HttpResponseRedirect, HttpResponse
from django.contrib.auth import logout
from django.core.urlresolvers import reverse
from smartstash.auth.models import ZoteroUser
import smartstash.core.zotero as zotero
from smartstash.core.utils import common_words

html_escapes = {
    "&": "&amp;",
    '"': "&quot;",
    "'": "&apos;",
    ">": "&gt;",
    "<": "&lt;",
    }

# Create your views here.

def zotero_oauth(request):
    request.session['oauth_verifier'] = request.GET['oauth_verifier']

    try:
        token, userid = zotero.access_info(request,
                                           request.GET['oauth_verifier'],
                                           request.session['request_token']
                                           )

        terms = zotero.get_user_items(request, userid, token, numItems=99)

        #tokenize
        search_terms = common_words("".join(terms['abstractSummary'] + terms['creatorSummary'] + terms['title']))

        #sanitize
        for key, val in search_terms.iteritems():
            search_terms[key] = [html_escapes.get(c, c) for c in val]

        request.session['search_terms'] = search_terms
        return HttpResponseRedirect(reverse('discoveries:view'))

    except:
        return HttpResponseRedirect(reverse('site-index'))


def logout_view(request):
    logout(request)
    return HttpResponseRedirect(reverse('site-index'))

def login_error(request):
    print 'request  ='
    print request

    return HttpResponse('there was a problem logging you in', content_type='text/plain')
