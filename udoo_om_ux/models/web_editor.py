# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

import base64
import logging
import re

from odoo.tools.misc import file_path, file_open
from odoo import api, models

_logger = logging.getLogger(__name__)


class ScssEditor(models.AbstractModel):
    _inherit = 'web_editor.assets'

    @property
    def DEF_OMLIGHT(self):
        return ''

    @property
    def ULIGHT(self):
        return '/udoo_om_ux/static/src/scss/omux/light.scss'

    @property
    def UDARK(self):
        return '/udoo_om_ux/static/src/scss/omux/dark.scss'

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Light
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_omux_light(self):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return
        curl = self._omux_asset_url(self.ULIGHT, 'web.assets_web')
        attachment = self.env['ir.attachment'].search([('url', '=', curl)])
        return attachment and base64.b64decode(attachment.datas) or self.DEF_OMLIGHT

    def set_omux_light(self, content):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return
        curl, asset = self._omux_bundle(content, 'scss', self.ULIGHT, 'web.assets_web')
        self.env.ref('udoo_om_ux.remove_light_in_dark').path = curl

    @api.model
    def reset_omux_light(self, pattern=None):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return
        if not pattern:
            self.env.ref('udoo_om_ux.remove_light_in_dark').path = self.ULIGHT
            self._omux_reset(self.ULIGHT, 'web.assets_web')
            return

        light_scss = self._omux_decode_scss(self.get_omux_light())
        if not light_scss:
            return
        scss_lines = []
        for line in light_scss.splitlines():
            if re.search(pattern, line) is None:
                scss_lines.append(line.strip())

        self.set_omux_light('\n'.join(scss_lines))

    @api.model
    def _remove_light_in_dark_correction(self):
        remove_light_asset = self.env.ref('udoo_om_ux.remove_light_in_dark', raise_if_not_found=False)
        if not remove_light_asset:
            return
        light_url = self._omux_asset_url(self.ULIGHT, 'web.assets_web')
        if self.env['ir.asset'].search([('path', '=', light_url)]):
            remove_light_asset.path = light_url

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Dark
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def get_omux_dark(self):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return
        curl = self._omux_asset_url(self.UDARK, 'web.assets_web_dark')
        attachment = self.env['ir.attachment'].search([('url', '=', curl)])
        return attachment and base64.b64decode(attachment.datas) or ''

    def set_omux_dark(self, content):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return
        self._omux_bundle(content, 'scss', self.UDARK, 'web.assets_web_dark')

    @api.model
    def reset_omux_dark(self, pattern=None):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return
        if not pattern:
            self._omux_reset(self.UDARK, 'web.assets_web_dark')
            return

        dark_scss = self._omux_decode_scss(self.get_omux_dark())
        if not dark_scss:
            return
        scss_lines = []
        for line in dark_scss.splitlines():
            if re.search(pattern, line) is None:
                scss_lines.append(line.strip())

        self.set_omux_dark('\n'.join(scss_lines))

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Theming
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    @api.model
    def extf_omux_scheme(self, var_names):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return

        light_result = {}
        dcss_index = self._build_dynamic_omux_varx(False)
        scss_index = self._build_static_omux_varx(dcss_index, False)
        for var_name in var_names:
            light_result[var_name] = self._resolve_scss_var(var_name, scss_index)

        dark_result = {}
        dcss_index = self._build_dynamic_omux_varx(True)
        scss_index = self._build_static_omux_varx(dcss_index, True)
        for var_name in var_names:
            dark_result[var_name] = self._resolve_scss_var(var_name, scss_index)

        return (light_result, dark_result)

    def _build_dynamic_omux_varx(self, dark=False):
        scss_index = {}
        variable_pattern = re.compile(
            r'^\s*\$([A-Za-z0-9_-]+)\s*:\s*(#[0-9A-Fa-f]+|\$[A-Za-z0-9_-]+)\s*!default;',
            flags=re.MULTILINE,
        )
        content = self._omux_decode_scss(self.get_omux_dark()) if dark else self._omux_decode_scss(self.get_omux_light())
        matches = variable_pattern.findall(content)
        for var_name, value in matches:
            if var_name not in scss_index:
                scss_index[var_name] = value

        return scss_index

    def _build_static_omux_varx(self, scss_index, dark=False):
        paths = self._omux_asset_paths(dark)

        variable_pattern = re.compile(
            r'^\s*\$([A-Za-z0-9_-]+)\s*:\s*(#[0-9A-Fa-f]+|\$[A-Za-z0-9_-]+)\s*!default;',
            flags=re.MULTILINE,
        )

        for path in self.env['ir.asset'].search([('path', 'ilike', f'omux_color_scheme%/scss/primary_variables{"_dark" if dark else ""}.scss')]).mapped('path') + paths:
            current_path = file_path(path)
            try:
                with file_open(current_path, 'rb') as f:
                    content = f.read().decode('utf-8')
                    matches = variable_pattern.findall(content)
                    for var_name, value in matches:
                        if var_name not in scss_index:
                            scss_index[var_name] = value
            except FileNotFoundError:
                continue

        return scss_index

    def _resolve_scss_var(self, var_name, scss_index, _visited=None):
        if _visited is None:
            _visited = set()

        if var_name in _visited:
            _logger.warning("Circular reference detected: '%s'", var_name)
            return ''
        _visited.add(var_name)

        value = scss_index.get(var_name)
        if not value:
            return ''

        if value.startswith('#'):
            return value
        elif value.startswith('$'):
            next_var = value.removeprefix('$').strip()
            return self._resolve_scss_var(next_var, scss_index, _visited)

        return ''

    @api.model
    def repr_omux_scheme(self, repl_dict, dark=False):
        if not self.env.user.has_group('udoo_om_ux.group_omux'):
            return

        scss_content = self._omux_decode_scss(self.get_omux_dark()) if dark else self._omux_decode_scss(self.get_omux_light())
        remove_keys = {repl_dict[k][0] for k in repl_dict}

        scss_lines = []
        for line in scss_content.splitlines():
            if not any(f'${key}:' in line for key in remove_keys):
                scss_lines.append(line.rstrip())

        # Append replacements clearly at the end
        scss_lines.append('')  # Ensure separation with an empty line
        for k in repl_dict:
            scss_lines.append(f'${repl_dict[k][0]}: {repl_dict[k][1]} !default; // Managed by Omux')

        if dark:
            self.set_omux_dark('\n'.join(scss_lines))
        else:
            self.set_omux_light('\n'.join(scss_lines))

    @api.model
    def repr_omux_font(self, params, asset_key='/_omux/backend_font.scss'):
        """
        Represent fonts for OMUX interface.
        Handle 3 cases: both fk+fs, only fk, or only fs exists in params.
        """
        if not params or not self.env.user.has_group('udoo_om_ux.group_omux'):
            return

        # Check what we have
        has_font = 'fk' in params and params['fk']
        has_size = 'fs' in params and params['fs']

        if not (has_font or has_size):
            return

        # Get current asset content if exists
        # Extract existing settings from attachment name
        existing_settings = {}
        if exist_asset := self.env['ir.asset'].search([('path', '=', asset_key)]):
            existing_settings = self._extract_font_settings(exist_asset.name)

        # Merge existing settings with new params
        merged_params = dict(existing_settings)
        for key, valid in (('fk', has_font), ('fs', has_size)):
            if params.get(key) == 'default':
                merged_params.pop(key, None)
            elif valid:
                merged_params[key] = params[key]

        if not merged_params:
            self.env['ir.attachment'].search([('url', '=', asset_key)]).unlink()
            self.env['ir.asset'].search([('path', '=', asset_key)]).unlink()
            return

        # Build content based on available params
        css_parts = []
        font_name = None

        if 'fk' in merged_params and merged_params['fk']:
            font_name = merged_params['fk'].split(':')[0].replace('+', ' ')
            css_parts.append(f"@import url('https://fonts.googleapis.com/css2?family={merged_params['fk']}');")
            css_parts.append(
                f'$o-system-fonts: ("{font_name}", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Ubuntu, "Noto Sans", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji") !default;'
            )

        if 'fs' in merged_params and merged_params['fs']:
            fs_dict = {
                'optimal': '0.9rem',
                'comfort': '0.938rem',
                'readable': '1rem',
                'large': '1.063rem',
            }
            fs_value = fs_dict.get(merged_params['fs'], '0.875rem')  # Default to 'default' if not found
            css_parts.append(f'$o-font-size-base: {fs_value} !default;')

        content = '\n'.join(css_parts)

        # Create appropriate naming
        name_components = []
        if font_name:
            name_components.append(f'Font: {font_name}')
        if 'fs' in merged_params and merged_params['fs']:
            name_components.append(f'Size: {merged_params["fs"]}')

        asset_name = 'Backend ' + ' + '.join(name_components)

        # Store the asset with metadata in name
        custom_url, target_asset = self._omux_bundle(content, 'scss', asset_name, 'web.assets_backend', 'prepend', asset_key)

        if target_asset:
            # Encode configuration in the name for state retrieval
            meta = []
            if 'fk' in merged_params and merged_params['fk']:
                meta.append(f'Font: {merged_params["fk"]}')
            if 'fs' in merged_params and merged_params['fs']:
                meta.append(f'Size: {merged_params["fs"]}')

            target_asset.write({'name': f'[OMUX] {" | ".join(meta)}'})

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Resolver
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def _omux_asset_paths(self, dark):
        if dark:
            return [
                'udoo_om_ux/static/src/webclient/navbar/start_menu.variables.dark.scss',
                'udoo_om_ux/static/src/webclient/navbar/start_menu.variables.scss',
                'udoo_om_ux/static/src/scss/primary_variables_dark.scss',
                'web/static/src/scss/primary_variables.scss',
            ]
        else:
            return [
                'udoo_om_ux/static/src/webclient/navbar/start_menu.variables.scss',
                'udoo_om_ux/static/src/scss/primary_variables.scss',
                'web/static/src/scss/primary_variables.scss',
            ]

    def _extract_font_settings(self, meta_string):
        result = {}
        if 'Font:' in meta_string:
            match = re.search(r'Font:\s*([^|]+)', meta_string)
            if match:
                result['fk'] = match.group(1).strip()

        if 'Size:' in meta_string:
            match = re.search(r'Size:\s*([^|]+)', meta_string)
            if match:
                result['fs'] = match.group(1).strip()

        return result

    def _omux_asset_url(self, url, bundle_xmlid):
        return f'/_omux/{bundle_xmlid}{url}'

    def _omux_reset(self, url, bundle):
        curl = self._omux_asset_url(url, bundle)
        self.env['ir.attachment'].search([('url', '=', curl)]).unlink()
        self.env['ir.asset'].search([('path', '=', curl)]).unlink()

    def _omux_bundle(self, content, type, url, bundle, directive='replace', custom_url=None):
        IrAsset = self.env['ir.asset'].sudo()
        IrAttachment = self.env['ir.attachment'].sudo()

        custom_url = custom_url or self._omux_asset_url(url, bundle)
        datas = base64.b64encode((content or '\n').encode('utf-8'))

        # Check if the file to save had already been modified
        custom_attachment = IrAttachment.search([('url', '=', custom_url)])
        if custom_attachment:
            # If it was already modified, simply override the corresponding
            # attachment content
            custom_attachment.write({'datas': datas})
            self.env.registry.clear_cache('assets')
        else:
            # If not, create a new attachment to copy the original scss/js file
            # content, with its modifications
            new_attach = {
                'name': custom_url or url.split('/')[-1],
                'type': 'binary',
                'mimetype': (type == 'js' and 'text/javascript' or 'text/scss'),
                'datas': datas,
                'url': custom_url,
            }
            IrAttachment.create(new_attach)

        # Create an asset with the new attachment
        target_asset = IrAsset.search([('path', '=', custom_url)])
        if not target_asset:
            new_asset = {
                'path': custom_url,
                'name': '[OMUX] ' + url,
                'bundle': bundle,
                'directive': directive,
                'sequence': 98,  # NOTE: Keep sequence >= 16 (DEFAULT_SEQUENCE)
            }
            if directive not in ['prepend', 'append', 'include']:
                new_asset['target'] = url
            target_asset = IrAsset.create(new_asset)
        return (custom_url, target_asset)

    def _omux_decode_scss(self, content):
        if isinstance(content, bytes):
            return content.decode('utf-8')
        return content or ''
