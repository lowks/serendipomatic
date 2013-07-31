from django import forms


class InputForm(forms.Form):

    text = forms.CharField(
        label='Copy and paste some text from an article.',
        help_text='Cut and paste a block of text. [Is this something that should go in a tooltip?]',
        widget=forms.Textarea,
        required=False)
        
    zotero_user = forms.CharField(
        label='Enter your Zotero username.',
        help_text="What kind of a loser doesn't know what Zotero is?",
        widget=forms.TextInput,
        required=False)

    # TODO: alternate inputs- zotero url?
    # use urlfield if appropriate
    # make text input not required, but add form validation
    # so at least one input is required for form to be valid

