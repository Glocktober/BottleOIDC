import os
import sys 

DEBUG = os.environ.get('DEBUG', False)

from bottle import request, response

def set_no_cache_headers():
    """
    Set various "no cache" headers for this response
    """

    # MDN recommended for various browsers
    response.add_header('Cache-Control', 'no-cache')
    response.add_header('Cache-Control', 'must-revalidate')
    response.add_header('Pragma', 'no-cache')
    response.add_header('Expires', 'Sun, 25 Jul 2021 15:42:14 GMT')


def url_for(name, _external=False):
    """
    mimic Flask url_for
    """
    path_part = request.app.get_url(name)
    if not _external:
        return path_part

    # External URL
    host_part = request.urlparts.scheme + '://' + request.urlparts.netloc
    url = host_part + path_part

    return url


def redirect(url, status=302):
    """ Update response for redirect """

    response.status = status
    response.add_header('Location', url)
    set_no_cache_headers()
    return None

#
# Assure consistent error responses
#
def response_error(status=401, body='', hdrs=None):
        response.status = status
        set_no_cache_headers()
        response.headers.update(hdrs or {})
        return body

def UnauthorizedError(body='Unauthorized'):
    return response_error(status=401, body=body)

def BadRequestError(body='Bad Request'):
    return response_error(status=400, body=body)

def AppError(body='App error'):
    return response_error(status=400, body=body)

def ConflictError(body='Conflict Error'):
    return response_error(status=400, body=body)

def ForbiddenError(body='Forbidden'):
    return response_error(status=403, body=body)

def NotFoundError(body='Not Found'):
    return response_error(status=404, body=body)

class _Log:
    """
    Mock logger - mocks logging with no bells and whistles
    """
    level = 'info'

    def info(self, *args, **kwargs):
        if self.level in ['info']:
            print('INFO -', *args, **kwargs, file=sys.stderr)

    def warn(self, *args, **kwargs):
        print('WARN -', *args, **kwargs, file=sys.stderr)

    def debug(self, *args, **kwargs):
        if DEBUG:
            print('DEBUG -', *args, **kwargs, file=sys.stderr)

    def error(self, *args, **kwargs):
        print('ERROR -', *args, **kwargs, file=sys.stderr)

