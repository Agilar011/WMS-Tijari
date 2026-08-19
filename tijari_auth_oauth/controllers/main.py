import json
import logging
import werkzeug.urls
from werkzeug.exceptions import BadRequest

from odoo import http, SUPERUSER_ID, _
from odoo.exceptions import AccessDenied
from odoo.http import request

from odoo.addons.auth_oauth.controllers.main import (
    OAuthController,
    OAuthLogin,
    fragment_to_query_string,
)
from odoo.addons.web.controllers.utils import (
    ensure_db,
    _get_login_redirect_url,
)
from odoo.tools.misc import clean_context

from ..exceptions import AccountNotRegistered

_logger = logging.getLogger(__name__)

class TijariOAuthController(OAuthController):

    @http.route('/auth_oauth/signin', type='http', auth='none', readonly=False)
    @fragment_to_query_string
    def signin(self, **kw):
        state = json.loads(kw['state'])

        dbname = state['d']
        if not http.db_filter([dbname]):
            raise BadRequest()

        ensure_db(db=dbname)

        provider = state['p']
        request.update_context(**clean_context(state.get('c', {})))

        try:
            _, login, key = (
                request.env['res.users']
                .with_user(SUPERUSER_ID)
                .auth_oauth(provider, kw)
            )

            request.env.cr.commit()

            action = state.get('a')
            menu = state.get('m')
            redirect = werkzeug.urls.url_unquote_plus(state['r']) if state.get('r') else False

            url = "/odoo"
            if redirect:
                url = redirect
            elif action:
                url = f"/odoo/action-{action}"
            elif menu:
                url = f"/odoo?menu_id={menu}"

            credential = {
                "login": login,
                "token": key,
                "type": "oauth_token",
            }

            auth_info = request.session.authenticate(dbname, credential)

            resp = request.redirect(
                _get_login_redirect_url(auth_info["uid"], url),
                303,
            )
            resp.autocorrect_location_header = False

            return resp

        except AccountNotRegistered:
            url = "/web/login?oauth_error=4"

        except AttributeError:
            _logger.exception("auth_signup not installed")
            url = "/web/login?oauth_error=1"

        except AccessDenied:
            _logger.info("OAuth access denied")
            url = "/web/login?oauth_error=3"

        except Exception:
            _logger.exception("Exception during OAuth")
            url = "/web/login?oauth_error=2"

        redirect = request.redirect(url, 303)
        redirect.autocorrect_location_header = False
        return redirect
    
class TijariOAuthLogin(OAuthLogin):

    @http.route()
    def web_login(self, *args, **kw):
        response = super().web_login(*args, **kw)

        if response.is_qweb and request.params.get("oauth_error") == "4":
            response.qcontext["error"] = _(
                "Your account is not registered.\n"
                "Please contact your administrator."
            )

        return response

    def list_providers(self):
        try:
            providers = request.env["auth.oauth.provider"].sudo().search_read([
                ("enabled", "=", True)
            ])
        except Exception:
            providers = []

        for provider in providers:
            return_url = request.httprequest.url_root + "auth_oauth/signin"
            state = self.get_state(provider)

            params = dict(
                response_type="token",
                client_id=provider["client_id"],
                redirect_uri=return_url,
                scope=provider["scope"],
                state=json.dumps(state),

                # Force Google account chooser
                prompt="select_account",
            )

            provider["auth_link"] = "%s?%s" % (
                provider["auth_endpoint"],
                werkzeug.urls.url_encode(params),
            )

            # _logger.warning(
            #     """
            # ========== GOOGLE OAUTH URL ==========
            # Provider : %s
            # Prompt   : %s
            # Auth URL :
            # %s
            # ======================================
            # """,
            #     provider["id"],
            #     params.get("prompt"),
            #     provider["auth_link"],
            # )

        return providers