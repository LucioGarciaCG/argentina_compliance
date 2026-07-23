import frappe, json
import datetime
import xml.etree.ElementTree as ET
from frappe import _dict
import subprocess
import requests
from zeep import Client
import os
from dateutil import parser
from argentina_compliance.argentina_compliance.doctype.electronic_invoice_log.electronic_invoice_log import (
    log_electronic_invoice_response,
)

def check_token_validity(row):
    """Check if the existing token is still valid"""
    try:
        # afip_settings = frappe.get_doc("AFIP Setting")
        if not row.token or not row.sign:
            return False
        
        # Get the expiration time from the token
        token_bytes = row.token.encode('utf-8')
        token_xml = ET.fromstring(token_bytes)
        expiration_time = token_xml.find('.//exp_time')
        
        if expiration_time is not None:
            expiration_time = datetime.datetime.fromtimestamp(int(expiration_time.text))
            
            current_time = datetime.datetime.now()
            
            # Return True if token is still valid (considering a small buffer)
            return current_time < (expiration_time - datetime.timedelta(minutes=10))
            
        return False
    except Exception:
        return False



# Roles allowed to generate or renew AFIP tokens. Generating a token signs a
# request with the company's AFIP private key, so this is deliberately narrow.
TOKEN_ROLES = ("System Manager", "Accounts Manager")


def _resolve_credentials_row(settings, row_data):
    """Find the real Credentials child row, server-side.

    ``row_data`` comes from the browser and is treated as untrusted: only its
    identifying fields are used to look the row up. The certificate and private
    key paths are always read from the stored document, never from the payload,
    so a caller cannot point openssl at an arbitrary file.
    """
    name = (row_data.get("name") or "").strip()
    company = (row_data.get("company") or "").strip()

    for row in settings.credentials:
        if name and row.name == name:
            return row

    # AFIPSetting.validate() enforces one credentials row per company.
    for row in settings.credentials:
        if company and row.company == company:
            return row

    frappe.throw("No AFIP credentials row found for the requested company")


@frappe.whitelist()
def get_afip_token(row):
    """Whitelisted entry point. Resolves the row server-side, then delegates."""
    frappe.only_for(TOKEN_ROLES)

    # Frappe hands whitelisted object args over as a JSON string, but accept a
    # mapping too: passing the wrong one of the two is what broke both
    # create_new_token() and renew_all_afip_tokens().
    row_data = _dict(json.loads(row)) if isinstance(row, str) else _dict(row)

    settings = frappe.get_doc("AFIP Setting")
    settings.check_permission("write")

    real_row = _resolve_credentials_row(settings, row_data)
    return _generate_token_for_row(settings, real_row)


def _generate_token_for_row(settings, row):
    """Request a WSAA token for ``row`` and persist it.

    ``row`` must be the real child Document out of ``settings.credentials``.
    Mutating a detached copy (for example a ``_dict`` from ``json.loads``) does
    not survive ``settings.save()`` — that is how the token used to come back
    successfully in the UI while the column stayed NULL in the database.
    """
    try:
        if not row.certificate:
            frappe.throw("Certificate field is empty in this credential row")
        if not row.private_key:
            frappe.throw("Private Key field is empty in this credential row")

        # Read from the stored document, never from the client payload.
        certificado = row.certificate  # e.g. '/private/files/finbyzCerficate.crt'
        clave_privada = row.private_key  # e.g. '/private/files/finbyz_key.key'

        # Convert to absolute paths
        certificado_path = frappe.get_site_path() + certificado
        clave_privada_path = frappe.get_site_path() + clave_privada
                
       
        if not os.path.exists(certificado_path):
            frappe.throw(f"Certificate not found: {certificado_path}")
        if not os.path.exists(clave_privada_path):
            frappe.throw(f"Private key not found: {clave_privada_path}")

        wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
        servicio_id = "wsfe"
        dt_now = datetime.datetime.utcnow()

        # Create XML structure
        root = ET.Element("loginTicketRequest")
        header = ET.SubElement(root, "header")
        unique_id = ET.SubElement(header, "uniqueId")
        generation_time = ET.SubElement(header, "generationTime")
        expiration_time = ET.SubElement(header, "expirationTime")
        service = ET.SubElement(root, "service")

        # WORKAROUND (clock skew): WSAA rejects a login ticket whose
        # generationTime it considers to be in the future. Between our clock,
        # network latency and AFIP's own clock, a generationTime of "now"
        # arrives a fraction of a second ahead and gets refused. Back-dating it
        # 10 minutes gives enough slack to absorb that.
        #
        # This is a workaround, not a fix: the real requirement is NTP on the
        # host. expirationTime is deliberately still computed from dt_now, so
        # the ticket keeps its normal 10-minute validity rather than expiring
        # the instant it is issued.
        generation_time.text = (dt_now - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        unique_id.text = dt_now.strftime("%y%m%d%H%M")
        service.text = servicio_id

        seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
        out_xml = f"{seq_nr}-LoginTicketRequest.xml"
        out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
        out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"
  
        # Sign CMS
        try:
            # Write XML to file
            xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
            with open(out_xml, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            
            # Sign CMS
            subprocess.run([
                'openssl', 'smime', '-sign',
                '-in', out_xml,
                '-signer', certificado_path,
                '-inkey', clave_privada_path,
                '-nodetach',
                '-outform', 'der',
                '-out', out_cms_der
            ], check=True)
            
            # Encode in BASE64
            subprocess.run([
                'openssl', 'base64',
                '-in', out_cms_der,
                '-e',
                '-out', out_cms_der_b64
            ], check=True)
            
            with open(out_cms_der_b64, 'r') as f:
                cms = f.read()
            
            # Call WSAA
            client = Client(wsaa_wsdl)
            wsaa_response = client.service.loginCms(cms)
            # Parse response and update settings
            response_root = ET.fromstring(wsaa_response)
            token = response_root.find('.//credentials/token').text
            sign = response_root.find('.//credentials/sign').text
            exp = response_root.find('.//header/expirationTime').text
            expiration_time = parser.isoparse(exp)
            expiration_time = expiration_time.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            
            # Mutate the real child Document, then save the parent. `row` is
            # attached to `settings`, so this actually reaches the database.
            if token and sign and expiration_time:
                row.token = token
                row.sign = sign
                row.expiration_time = expiration_time
                settings.save()

                frappe.msgprint(f"AFIP token and sign updated successfully")
                # Success log. The token and sign are credentials: they are
                # never written to the log, which is readable in the UI and
                # persisted in the database. Log status and validity only.
                log_electronic_invoice_response(
                    doctype="AFIP Setting",
                    title=f"AFIP token and sign Renewed successfully valid till {expiration_time}",
                    status="Success",
                    message=(
                        f"Company : {row.company}\n"
                        f"CUIT : {row.cuit}\n"
                        f"Valid Till : {expiration_time}"
                    ),
                )
                return {"success": True, "token": token, "sign": sign, "expiration_time":expiration_time}
            else:
                frappe.error_log(f"Token Renew Failed: " )

        except Exception as e:
            frappe.log_error(
                f"AFIP Token Scheduled renewal Error: {str(e)}")
            frappe.msgprint(
              
                f"Error in AFIP Scheduled renewal Error: {str(e)}\n\n"
                f"Stored Expiration: {row.expiration_time or 'Not Set'}"
            )
        finally:
                # Cleanup temporary files
                for file in [out_xml, out_cms_der, out_cms_der_b64]:
                    if os.path.exists(file):
                        os.remove(file)
                        
    except Exception as e:

        frappe.log_error(f"AFIP Token Scheduled renewal Error: {str(e)}")
        frappe.throw(f"Error in AFIP token Scheduled renewal: {str(e)}")
        return {"success": False, "message": str(e)}
    


@frappe.whitelist()
def renew_all_afip_tokens():
    """Scheduled every 12h from hooks.py, and callable from the UI.

    Iterates the credentials rows and calls the helper directly. It used to
    call get_afip_token(row), passing a Document where a JSON string was
    expected, which raised TypeError on the first row — so the scheduled
    renewal never actually ran.
    """
    if frappe.session.user != "Administrator":
        frappe.only_for(TOKEN_ROLES)

    settings = frappe.get_doc("AFIP Setting")

    for row in settings.credentials:
        if not (row.cuit and row.certificate and row.private_key):
            continue
        try:
            _generate_token_for_row(settings, row)
        except Exception:
            # One bad company must not stop the others from renewing.
            frappe.log_error(
                title=f"AFIP token renewal failed for {row.company}",
                message=frappe.get_traceback(),
            )
   