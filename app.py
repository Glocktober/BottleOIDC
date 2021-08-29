import json
import os
import sys

sys.path.insert(0,os.getcwd())

import jwt 

from bottle import Bottle, request, response
from BottleSessions import BottleSessions
from BottleOIDC import BottleOIDC

from config import oidc_config

DEBUG = os.environ.get('DEBUG', False)

app = Bottle()
BottleSessions(app, session_expire=4*60*60, session_backing={
    'cache_type': 'FileSystem', 
    'cache_dir': './.cache_dir'
})

auth = BottleOIDC(app, config=oidc_config)

#
# Authentication: require_login decorator
#
@app.route(['/login','/logon'])
@auth.require_login
def login():
    """ Login """

    return {'username': request.session['username']}

#
# logout 
#
@app.route(['/logout','/logoff'])
def bye():
    """ Logout """

    if auth.is_authenticated:
        return auth.initiate_logout(next=request.url)
    else:
        return 'ok'

#
# Authorization: require_user decorator
#
@app.route('/bob')
@auth.require_user(['bob','r.r.kras'])
def bob():
    """ Only bob """
    return 'hi bob'

#
# Authorization: require_attribute decorator
#
@app.route('/sa')
@auth.require_attribute('groups', ['netadmin', 'sysadmin'])
def sa():
    return 'hi sa'


if DEBUG:
    # DEBUG helpers

    print(auth.scopes_supported)
    @app.route('/.sess')
    def status():
        """ Return entire session """
        response.set_header('Content-Type', 'text/plain')
        return json.dumps(request.session, indent=4)


    @app.route('/.exp')
    def expire():
        """ Hasten token expiration by 1 hr. """
        request.session[auth.token_name]['exp'] -= 3600
        request.session.session_modified = True
        return 'ok'


    def decode_jwt(token):
        """ decode and return token response. """

        payload = jwt.decode(token, options={'verify_signature': False})
        response.set_header('Content-Type', 'text/plain')
        return json.dumps(payload, indent=4)


    @app.route(['/<pat>/.id','/.id'])
    def id_tok(pat=auth.token_name):
        """ decode id token """

        return decode_jwt(request.session[pat]['id_token'])


    @app.route(['/<pat>/.access','/.access'])
    def ac_tok(pat=auth.token_name):
        """ decode access token """

        return decode_jwt(request.session[pat]['access_token'])


    @app.route(['/.meh','/.meh/'])
    def meh_token():
        """ Request new tokens with new scope. """
        scp = request.query.get('scp')
        tokens = auth.get_access_token('meh', scope=scp)
        return {'tokens': tokens}


if __name__ == '__main__':
    app.run(port=8000, debug=DEBUG, reloader=DEBUG)
