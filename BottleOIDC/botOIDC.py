import time
from urllib.parse import urlencode

import requests as req
from bottle import request

from .oidc_discover import OidcDiscover
from .oidc_state import OIDCstate
from .bottle_utils import (
        redirect, 
        UnauthorizedError, 
        BadRequestError, 
        ConflictError,
        url_for,
        _Log
    )

default_oidc_scope = ['openid', 'email', 'profile']
default_user_attr = 'email'

now = lambda : int(time.time())


class BottleOIDC(OidcDiscover):
    """
    auth = BottleOIDC(app, config, ...)

    OIDC Service Provider for Bottle
    Uses Authorization Code Grant flow

    """

    def __init__( self,
            app, 
            config,
            sess_username = 'username',
            sess_attr = 'oidc_attr',
            log=None,
        ):

        self.app = app

        self.logger = log if log else _Log()

        self.client_id = config['client_id']
        self.client_secret = config['client_secret']
        self.scopes = config.get('client_scope', default_oidc_scope)
        self.username_id = config.get('user_attr', default_user_attr)

        self.token_name = 'oidc_tokens'
        self.sess_username = sess_username
        self.sess_attr = sess_attr

        # autodiscovery of oidc config in base class
        discovery_url = config['discovery_url']
        timeout = config.get('timeout', 4)      # undocumented
        super().__init__(discovery_url, timeout=timeout)

        # msft special - 'offline_access' provides refresh tokens
        if 'offline_access' in self.scopes_supported:
            self.scopes.append('offline_access')
        
        # initialize state creator # state_key and state_ttl undocumented
        self.state = OIDCstate(key=config.get('state_key'), ttl=config.get('state_ttl',60))

        # OIDC authorized - receives code grant redirect form IdP via client
        app.route(path='/oidc/authorized', name='authorized', callback=self._finish_oauth_login)
        
        self.login_hooks = [self._id_token_hook]

        if not config.get('logout_idp',False):
            # Local logout only (i.e. don't notify IdP)
            self.logout_url = None


    @property
    def is_authenticated(self):
        """ True if user has authenticated. """

        return self.sess_username in request.session and request.session[self.sess_username]


    @property
    def my_username(self):
        """ Return username for the current session. """

        return request.session[self.sess_username] if self.is_authenticated else None
    

    @property
    def my_attrs(self):
        """ Return collected assertions for the current session. """

        return request.session[self.sess_attr] if self.is_authenticated else {}
    

    def initiate_login(self, next=None, scopes=None, **kwargs):
        """ Initiate an OIDC/Oauth2 login. (return a redirect.) """

        # 'next' url - return to this after tokens acquired.
        state = {
            'next': next if next else request.params.get('next','/')
        }

        params = {
            'client_id' : self.client_id,
            'response_type' : 'code',
            'redirect_uri' : url_for('authorized', _external=True),
            'response_mode': 'query',
            'scope' : ' '.join(scopes if scopes else self.scopes),
            'state' : self.state.serial(state),
        }
        
        # These are microsoft Azure AD login extentensions
        if request.params.get('login_hint'):
            params.update({'login_hint': request.params.get('login_hint')})
        
        if kwargs.get('userhint'):
            # priority over any in request query string
            params.update({'login_hint': kwargs.get('userhint')})
        
        if request.params.get('domain_hint'):
            params.update({'domain_hint': request.params.get('domain_hint')})

        if request.params.get('prompt'):
            params.update({'prompt': request.params.get('prompt')})
        
        if kwargs.get('force_reauth'):
            params.update({'prompt':'login'})

        return redirect(self.auth_url + '?' + urlencode(params))


    # route: /authorized
    def _finish_oauth_login(self):
        """ Callback Route: Complete login by obtaining id and access tokens. """

        if 'error' in request.params:
            msg = f'OIDC: AuthNZ error: {request.params.get("error_description")}'
            self.logger.info(msg)
            return BadRequestError(msg)

        try:
            # Validate and deserialize state
            state = self.state.deserial(request.params.get('state'))

        except Exception as e:
            msg = 'OIDC: Authentication request was not outstanding'
            self.logger.info(msg, str(e))
            return BadRequestError(msg)

        code = request.params.get('code')

        # Prepare to exchange code for tokens
        params = {
            'client_id' : self.client_id,
            'client_secret' : self.client_secret,
            'grant_type' : 'authorization_code',
            'code': code,
            'redirect_uri' : url_for('authorized', _external=True),
        }
        
        try:
            self.logger.debug(f'OIDC: exchanging code {code[:10]}...{code[-10:]} for tokens')
            resp = req.post(self.token_url, data=params, timeout=self.timeout)
            tokens = resp.json()
            
            if 'error' in tokens:
                msg = f'OIDC: error exchanging code for tokens: {tokens["error_description"]}'
                self.logger.info(msg)
                return ConflictError(msg)
            
            try:
                # authenticate and decode the id token
                idtok = self.jwks.decode(tokens['id_token'], audience=self.client_id)
                
                tokens['exp'] = idtok['exp']
                request.session[self.token_name] = tokens

                username = idtok.get(self.username_id, 'Authenticated User')       
                attrs = idtok

                # Run all login hooks
                for login_hook in self.login_hooks:
                    username, attrs = login_hook(username, attrs)

                attrs.update({
                    'authenticated' : now()
                })
                
                self.logger.info(f'OIDC: User "{username}" authenticated')
                request.session[self.sess_attr] = attrs
                request.session[self.sess_username] = username

            except Exception as e:
                self.logger.info(f'Error: OIDC: failed to verify token: {str(e)}')
                return UnauthorizedError('OIDC: failed to verify id token')

        except Exception as e:
            self.logger.info(f'Error: OIDC: token acquisition failed: {str(e)}')
            return UnauthorizedError('OIDC: Error acquiring id token')

        if 'next' in state:
            return redirect(state['next'])
        else:
            return f'OIDC: authenticated "{username}"'


    def initiate_logout(self, next=None):
        """ Clear session and redirect to provider logout. """

        if next is None:
            next = request.params.get('next') 

        if self.is_authenticated:
            user = self.my_username
        else:
            user = 'Anonymous'
        
        self.logger.info(f'OIDC: user "{user}" logged out')

        # since we did the authentication, we should do this:
        request.session.session_delete()

        if self.logout_url and next:
            return redirect(self.logout_url +'?' + urlencode({'post_logout_redirect_uri': next}))

        elif self.logout_url:
            return redirect(self.logout_url)

        elif next:
            return redirect(next)

        else:
            return 'Logout complete'


    def _token_expire_check(self, token_name=None):
        """ Refresh token if needed. """
        
        if not token_name:
            # default is the base authenticator tokens
            token_name = self.token_name
        
        if now() < request.session[token_name]['exp']:
            # The tokens are still valid
            return True

        self.logger.debug(f'OIDC: Auto-refreshing expired "{token_name}" token')

        tokens = self._get_token_with_refresh(token_name)

        if tokens:
            idtok = self.jwks.decode(tokens['id_token'], options={'verify_signature':False})

            tokens['exp'] = idtok['exp']
            request.session[token_name] = tokens

            self.logger.debug(f'OIDC: Token refreshed')
            return True
        
        else:
            self.logger.info(f'OIDC: session token refresh for "{token_name}" failed.')
            return False


    def _get_token_with_refresh(self, token_name=None, scope=None):
        """ Get a new tokens using the refresh token. """
        
        if not token_name:
            # default is the base authenticator tokens
            token_name = self.token_name
        
        if token_name in request.session:
            current_tokens = request.session[token_name]
        else:
            # this is a new token_name, use the oidc tokens for refresh
            current_tokens = request.session[self.token_name]
        
        if 'refresh_token' not in current_tokens:
            # we don't have a refresh token to use
            return None

        params = {
            'client_id' : self.client_id,
            'client_secret' : self.client_secret,
            'grant_type' : 'refresh_token',
            'refresh_token' : current_tokens['refresh_token'],
        }

        if scope:
            # specific scope is requested
            params.update({'scope': scope})
        
        resp = req.post(self.token_url, data=params)
        new_tokens = resp.json()
        
        if 'error' in new_tokens:
            # There was a failure
            self.logger.debug(f'OIDC: Error: refreshing tokens: {new_tokens["error_description"]}')
            return None
        
        idtok = self.jwks.decode(new_tokens['id_token'], options={'verify_signature' :False})
        
        new_tokens['exp'] = idtok['exp']

        return new_tokens


    def _id_token_hook(self, user, attr):
        """ Remove unneeded id_token data from session attributes """

        for key in ['aud', 'iss', 'iat', 'nbf', 'exp', 'aio', 'tid','uti', 'ver', 'wids']:
            if key in attr: del attr[key]

        # username part of email:
        user = user.split('@')[0]

        # Add username as an attribute as well   
        attr['username'] = user

        return user, attr


    def get_access_token(self, token_name=None, scope=None):
        """ Get and cache an access_token for given scopes. """
        
        if not token_name:
            # default is the base authenticator tokens
            token_name = self.token_name

        if token_name in request.session and request.session[token_name]['exp'] < now():
            # this token is expired - remove it
            del request.session[token_name]

        if token_name in request.session:
            # return the current cached token
            return request.session[token_name]

        else:
            # nothing cached, get a new token
            new_tokens = self._get_token_with_refresh(scope=scope)

            if new_tokens:
                # token is valid, so save it
                request.session[token_name] = new_tokens
                return new_tokens
            else:
                # no token provided - just to be explicit
                return None
    

    # api: @auth.require_login decorator.
    def require_login(self, f):
        """ Decorator for forcing authenticated. """

        def _wrapper(*args, **kwargs):

            if self.is_authenticated and self.token_name in request.session:
                
                if self._token_expire_check(self.token_name):

                    return f(*args, **kwargs)

            # either no user in this session or a refresh failed - full login...
            return self.initiate_login(next = request.url)

        _wrapper.__name__ = f.__name__
        return _wrapper
    

    def add_login_hook(self,f):
        """ Decorator for adding login hook. """

        self.login_hooks.append(f)           
        return f


    def require_user(self, user_list):
        """ Decorator passes on specific list of usernames. """

        def _outer_wrapper(f):

            def _wrapper(*args, **kwargs):
                if self.my_username in user_list:
                    return f(*args, **kwargs)
                
                return UnauthorizedError('Not Authorized')
            
            _wrapper.__name__ = f.__name__
            return _wrapper
        
        return _outer_wrapper
                

    def require_attribute(self, attr, value):
        """ Decorator requires specific attribute value. """

        def test_attrs(challenge, standard):
            """Compare list or val the standard."""

            stand_list = standard if type(standard) is list else [standard]
            chal_list = challenge if type(challenge) is list else [challenge]

            for chal in chal_list:
                if chal in stand_list:
                    return True
            return False
        
        def _outer_wrapper(f):

            def _wrapper(*args, **kwargs):

                if attr in self.my_attrs:
                    resource = request.session[self.sess_attr][attr]
                    
                    if test_attrs(resource, value):
                            return f(*args, **kwargs)

                return UnauthorizedError('Not Authorized')

            _wrapper.__name__ = f.__name__
            return _wrapper

        return _outer_wrapper


