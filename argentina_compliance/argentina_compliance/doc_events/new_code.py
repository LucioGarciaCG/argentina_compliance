import frappe
import datetime
import xml.etree.ElementTree as ET
import subprocess
import requests
from zeep import Client
import os


def check_token_validity(row):
    """Check if the existing token is still valid"""
    try:
        if not row.token or not row.sign:
            return False

        # If no expiration time, consider token invalid
        if not hasattr(row, 'expiration_time') or not row.expiration_time:
            return False
            
        # Check if token is still valid
        current_time = datetime.datetime.now()
        is_valid = current_time < (row.expiration_time - datetime.timedelta(minutes=10))
        return is_valid
            
    except Exception:
        return False


def get_afip_token(row_name):
    print("=== STARTING get_afip_token ===")
    try:
        print(f"Input row_name: {row_name}, type: {type(row_name)}")
        
        # If row_name is a string, get the actual row object
        if isinstance(row_name, str):
            settings = frappe.get_doc("AFIP Setting")
            row = next((r for r in settings.credentials if r.name == row_name), None)
            if not row:
                frappe.throw(f"Credentials row with name '{row_name}' not found")
        else:
            row = row_name
            
        if not row:
            frappe.throw("Credentials row not found")
        
        # 1) USE VALID TOKEN
        if check_token_validity(row):
            frappe.msgprint(f"Using existing valid token for row {row}")
            return {"success": True, "token": row.token, "sign": row.sign}

        # 2) GENERATE NEW TOKEN
        site_path = frappe.get_site_path()
        servicio_id = "wsfe"
        
        certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
        clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')
        
        if not os.path.exists(certificado):
            frappe.throw(f"Certificate not found: {certificado}")
        if not os.path.exists(clave_privada):
            frappe.throw(f"Private key not found: {clave_privada}")

        wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
        dt_now = datetime.datetime.utcnow()

        # XML creation
        root = ET.Element("loginTicketRequest")
        header = ET.SubElement(root, "header")
        unique_id = ET.SubElement(header, "uniqueId")
        generation_time = ET.SubElement(header, "generationTime")
        expiration_time = ET.SubElement(header, "expirationTime")
        service = ET.SubElement(root, "service")

        generation_time.text = dt_now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        unique_id.text = dt_now.strftime("%y%m%d%H%M")
        service.text = servicio_id

        seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
        out_xml = f"{seq_nr}-LoginTicketRequest.xml"
        out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
        out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"

        try:
            # Write XML to file
            xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
            with open(out_xml, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            
            # Sign CMS
            subprocess.run([
                'openssl', 'smime', '-sign',
                '-in', out_xml,
                '-signer', certificado,
                '-inkey', clave_privada,
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
            try:
                wsaa_response = client.service.loginCms(cms)
                print("wsaa_response", wsaa_response)
            except Exception as soap_error:
                error_msg = str(soap_error)
                print(f"SOAP Error: {error_msg}")
                
                # Check for AFIP-specific errors
                if "ya posee un ta valido" in error_msg.lower() or "cee ya posee un ta valido" in error_msg.lower():
                    frappe.msgprint("AFIP says token already exists. Using existing token if available.")
                    if row.token and row.sign:
                        return {"success": True, "token": row.token, "sign": row.sign}
                    else:
                        # Clear any existing tokens and wait before retry
                        frappe.msgprint("AFIP has token but database doesn't. Clearing and will retry in next call.")
                        # row.token = None
                        # row.sign = None
                        # row.expiration_time = None
                        # settings = frappe.get_doc("AFIP Setting")
                        # settings.save()
                        # frappe.db.commit()
                        return {"success": False, "message": "Token cleared. Please try again in a few minutes."}
                elif "schema" in error_msg.lower() or "xml" in error_msg.lower():
                    frappe.throw(f"XML Schema error: {error_msg}. Check XML format.")
                elif "certificate" in error_msg.lower() or "cert" in error_msg.lower():
                    frappe.throw(f"Certificate error: {error_msg}")
                elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                    frappe.throw(f"Connection error to AFIP: {error_msg}")
                else:
                    frappe.throw(f"AFIP WSAA Error: {error_msg}")
            
            # Parse response and update settings
            try:
                response_root = ET.fromstring(wsaa_response)
                print("XML parsed successfully")
                print(f"Root element: {response_root.tag}")
                
                # Debug: Print all elements in the response
                print("All elements in response:")
                for elem in response_root.iter():
                    print(f"  Tag: {elem.tag}, Text: {elem.text}")
                
                # Try different XPath patterns
                token_elem = response_root.find('.//token')
                if token_elem is None:
                    token_elem = response_root.find('.//credentials/token')
                if token_elem is None:
                    # Try without namespace prefix
                    for elem in response_root.iter():
                        if elem.tag.endswith('token') or 'token' in elem.tag.lower():
                            token_elem = elem
                            print(f"Found token element: {elem.tag}")
                            break
                
                sign_elem = response_root.find('.//sign')
                if sign_elem is None:
                    sign_elem = response_root.find('.//credentials/sign')
                if sign_elem is None:
                    for elem in response_root.iter():
                        if elem.tag.endswith('sign') or 'sign' in elem.tag.lower():
                            sign_elem = elem
                            print(f"Found sign element: {elem.tag}")
                            break
                
                expiration_elem = response_root.find('.//expirationTime')
                if expiration_elem is None:
                    expiration_elem = response_root.find('.//header/expirationTime')
                if expiration_elem is None:
                    for elem in response_root.iter():
                        if 'expiration' in elem.tag.lower():
                            expiration_elem = elem
                            break
                
                print(f"Token element found: {token_elem is not None}")
                print(f"Sign element found: {sign_elem is not None}")
                
                if token_elem is not None and sign_elem is not None:
                    token = token_elem.text
                    sign = sign_elem.text
                    print(f"Extracted token: {token[:20] if token else 'None'}...")
                    print(f"Extracted sign: {sign[:20] if sign else 'None'}...")
                    
                    if expiration_elem is not None:
                        expiration = expiration_elem.text
                        try:
                            expiration_dt = datetime.datetime.strptime(expiration, "%Y-%m-%dT%H:%M:%S.%fZ")
                        except ValueError:
                            expiration_dt = datetime.datetime.strptime(expiration, "%Y-%m-%dT%H:%M:%SZ")
                    else:
                        expiration_dt = datetime.datetime.utcnow() + datetime.timedelta(hours=12)
                    
                    print(f"Token: {token[:50]}...")
                    print(f"Sign: {sign[:50]}...")
                    print(f"Expiration date: {expiration_dt}")
                    
                    # SAVE IN ROW
                    row.token = token
                    row.sign = sign
                    row.expiration_time = expiration_dt
                    
                    settings = frappe.get_doc("AFIP Setting")
                    settings.save()
                    frappe.db.commit()
                    
                    return {"success": True, "token": token, "sign": sign}
                else:
                    # If we can't parse the response but got one, set basic expiration
                    if row.token and row.sign:
                        row.expiration_time = datetime.datetime.now() + datetime.timedelta(hours=12)
                        settings = frappe.get_doc("AFIP Setting")
                        settings.save()
                        frappe.db.commit()
                    frappe.throw("Could not find token or sign in WSAA response")
                    
            except ET.ParseError as e:
                frappe.throw(f"Failed to parse WSAA response XML: {str(e)}")
            except Exception as e:
                frappe.throw(f"Error processing WSAA response: {str(e)}")

        except Exception as e:
            frappe.log_error(f"AFIP Token Error: {str(e)}")
            frappe.msgprint(f"Error generating token: {str(e)}")
            return {"success": False, "message": str(e)}

        finally:
            for file in [out_xml, out_cms_der, out_cms_der_b64]:
                if os.path.exists(file):
                    os.remove(file)
                        
    except Exception as e:
        frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
        frappe.throw(f"Error in AFIP token generation: {str(e)}")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def renew_all_afip_tokens():
    print("=== STARTING renew_all_afip_tokens ===")
    settings = frappe.get_doc("AFIP Setting")
    print(settings.credentials[:1])
    for row in settings.credentials[:1]:
        print(f"Checking row: {row}")
        if not check_token_validity(row):
            print(f"Token expired. Calling get_afip_token")
            frappe.logger().info(f"[AFIP Scheduler] Token expired. Regenerating for row {row.idx}")
            result = get_afip_token(row)
            print(f"Result: {result}")
        else:
            print(f"Token is valid")
            frappe.logger().info(f"[AFIP Scheduler] Token valid for row {row.idx}")
    print("=== FINISHED renew_all_afip_tokens ===")