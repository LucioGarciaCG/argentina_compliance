import frappe
import datetime
import xml.etree.ElementTree as ET
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



#Old and Correct Code
def get_afip_token(row):
    try:
        settings = frappe.get_doc("AFIP Setting")
        
        if not row:
            frappe.throw("Credentials row not found")
        
        servicio_id = "wsfe"
        
        if not row.certificate:
            frappe.throw("Certificate field is empty in this credential row")
        if not row.private_key:
            frappe.throw("Private Key field is empty in this credential row")

                
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

        generation_time.text = (dt_now).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
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
            
            # SAVE IN ROW ONLY
            if token and sign and expiration_time:
                row.token = token
                row.sign = sign
                row.expiration_time = expiration_time
                settings.save()

                frappe.msgprint(f"AFIP token and sign updated successfully")
                #Create Success Log 
                log_electronic_invoice_response(
                    doctype="AFIP Setting",
                    title=f"AFIP token and sign Renewed successfully valid till {expiration_time}",
                    status="Success",
                    message=(
                        f"Token : {token}\nSign : {sign}\nValid Till : {expiration_time}"
                    ),
                )
                return {"success": True, "token": token, "sign": sign}
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
    settings = frappe.get_doc("AFIP Setting")
    for row in settings.credentials:
        if row.cuit and row.certificate and row.private_key:
            get_afip_token(row)
   