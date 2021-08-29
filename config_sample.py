
# Example configuration template
oidc_config = {
    "client_id": "IDP Provided Client ID",
    "client_secret": "IDP Provided Secret",
    "discovery_url": "https://login.microsoftonline.com/<tenentid>/V2.0/.well-known/openid-configuration",
    "client_scope": ["openid", "email", "profile", ],
    "user_attr": 'email'
}