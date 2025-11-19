import frappe
import datetime
import xml.etree.ElementTree as ET
import subprocess
import requests
from zeep import Client
import os

def check_token_validity():
    """Check if the existing token is still valid"""
    try:
        afip_settings = frappe.get_doc("AFIP Setting")
        if not afip_settings.token or not afip_settings.sign:
            return False
        
        # Get the expiration time from the token
        token_bytes = afip_settings.token.encode('utf-8')
        token_xml = ET.fromstring(token_bytes)
        expiration_time = token_xml.find('.//exp_time')
        
        if expiration_time is not None:
            expiration_time = datetime.datetime.fromtimestamp(int(expiration_time.text))
            current_time = datetime.datetime.now()
            f"Row {row.idx}: Error generating token.<br>"
            
            # Return True if token is still valid (considering a small buffer)
            return current_time < (expiration_time - datetime.timedelta(minutes=10))
            
        return False
    except Exception:
        return False


def get_afip_token():
    try:
        # First check if we have a valid token
        if check_token_validity():
            frappe.msgprint("Using existing valid AFIP token")
            afip_settings = frappe.get_doc("AFIP Setting")
            return {
                "success": True,
                "token": afip_settings.token,
                "sign": afip_settings.sign
            }
        
        # If no valid token exists, proceed with generating a new one
        site_path = frappe.get_site_path()
        
        # Set the service ID (replace with your actual service ID)
        servicio_id = "wsfe"
        
        # Set certificate and private key paths
        certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
        clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')
        
        # Verify files exist
        if not os.path.exists(certificado):
            frappe.throw(f"Certificate file not found at {certificado}")
        if not os.path.exists(clave_privada):
            frappe.throw(f"Private key file not found at {clave_privada}")
        
        # Set WSDL URL
        wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
        
        # Create XML access ticket
        dt_now = datetime.datetime.utcnow()
        
        # Create XML structure
        root = ET.Element("loginTicketRequest")
        header = ET.SubElement(root, "header")
        unique_id = ET.SubElement(header, "uniqueId")
        generation_time = ET.SubElement(header, "generationTime")
        expiration_time = ET.SubElement(header, "expirationTime")
        service = ET.SubElement(root, "service")
        
        # Set times using proper UTC format
        generation_time.text = (dt_now).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
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
            wsaa_response = client.service.loginCms(cms)
            
            # Parse response and update settings
            response_root = ET.fromstring(wsaa_response)
            token = response_root.find('.//credentials/token').text
            sign = response_root.find('.//credentials/sign').text
            
            afip_settings = frappe.get_doc("AFIP Setting")
            afip_settings.token = token
            afip_settings.sign = sign
            afip_settings.save()
            
            frappe.db.commit()
            
            frappe.msgprint("AFIP token and sign updated successfully")
            
            return {
                "success": True,
                "token": token,
                "sign": sign
            }
            
        except Exception as e:
            frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
            frappe.throw(f"Error generating AFIP token: {str(e)}")
            
        finally:
            # Cleanup temporary files
            for file in [out_xml, out_cms_der, out_cms_der_b64]:
                if os.path.exists(file):
                    os.remove(file)
                    
    except Exception as e:
        frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
        frappe.throw(f"Error in AFIP token generation: {str(e)}")
        
        

#Old and Correct Code

# def get_afip_token(row_name):
#     # frappe.throw("hello")
#     try:
#         settings = frappe.get_doc("AFIP Setting")
        
#         # Find the child row
#         row = next((r for r in settings.credentials if r.name == row_name), None)
#         if not row:
#             frappe.throw("Credentials row not found")
        
#         # 1) USE VALID TOKEN
#         if check_token_validity(row):
#             frappe.msgprint(f"Using existing valid token for row {row_name}")
#             return {"success": True, "token": row.token, "sign": row.sign}

#         # 2) GENERATE NEW TOKEN
#         site_path = frappe.get_site_path()
        
#         # Set the service ID (replace with your actual service ID)
#         servicio_id = "wsfe"
        
#         certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
#         clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')
        
#         if not os.path.exists(certificado):
#             frappe.throw(f"Certificate not found: {certificado}")
#         if not os.path.exists(clave_privada):
#             frappe.throw(f"Private key not found: {clave_privada}")

#         wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
#         servicio_id = "wsfe"
#         dt_now = datetime.datetime.utcnow()

#         # XML creation
#         # Create XML structure
#         root = ET.Element("loginTicketRequest")
#         header = ET.SubElement(root, "header")
#         unique_id = ET.SubElement(header, "uniqueId")
#         generation_time = ET.SubElement(header, "generationTime")
#         expiration_time = ET.SubElement(header, "expirationTime")
#         service = ET.SubElement(root, "service")

#         generation_time.text = (dt_now).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         unique_id.text = dt_now.strftime("%y%m%d%H%M")
#         service.text = servicio_id

#         seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
#         out_xml = f"{seq_nr}-LoginTicketRequest.xml"
#         out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
#         out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"
        

#         # Sign CMS
#         try:
#             # Write XML to file
#             xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
#             with open(out_xml, 'w', encoding='utf-8') as f:
#                 f.write(xml_content)
            
#             # Sign CMS
#             subprocess.run([
#                 'openssl', 'smime', '-sign',
#                 '-in', out_xml,
#                 '-signer', certificado,
#                 '-inkey', clave_privada,
#                 '-nodetach',
#                 '-outform', 'der',
#                 '-out', out_cms_der
#             ], check=True)
            
#             # Encode in BASE64
#             subprocess.run([
#                 'openssl', 'base64',
#                 '-in', out_cms_der,
#                 '-e',
#                 '-out', out_cms_der_b64
#             ], check=True)
            
#             with open(out_cms_der_b64, 'r') as f:
#                 cms = f.read()
            
#             # Call WSAA
#             client = Client(wsaa_wsdl)
#             wsaa_response = client.service.loginCms(cms)
            
#             # Parse response and update settings
#             response_root = ET.fromstring(wsaa_response)
#             token = response_root.find('.//credentials/token').text
#             sign = response_root.find('.//credentials/sign').text
            
#             # SAVE IN ROW ONLY
#             row.token = token
#             row.sign = sign
#             # frappe.throw(str(row.token))
#             settings.save()
#             frappe.db.commit()
            

#             frappe.msgprint(f"New token generated for row {row_name}")
#             return {"success": True, "token": token, "sign": sign}

#         except Exception as e:
#             frappe.log_error(f"AFIP Token Error: {str(e)}")
#             frappe.msgprint(f"Error generating token: {str(e)}")

#         finally:
#                 # Cleanup temporary files
#                 for file in [out_xml, out_cms_der, out_cms_der_b64]:
#                     if os.path.exists(file):
#                         os.remove(file)
                        
#     except Exception as e:
#         frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
#         frappe.throw(f"Error in AFIP token generation: {str(e)}")
    



# def get_afip_token_scheduler(row):
#     """Generate or reuse AFIP token for the given row object"""

#     try:
#         settings = frappe.get_doc("AFIP Setting")
        
#         # ----- 1) USE EXISTING VALID TOKEN -----
#         if check_token_validity(row):
#             frappe.msgprint(f"Using existing valid token for row {row.name}")
#             print("row")
#             return {"success": True, "token": row.token, "sign": row.sign}

#         # ----- 2) GENERATE NEW TOKEN -----
#         site_path = frappe.get_site_path()
#         servicio_id = "wsfe"

#         certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
#         clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')
        
#         if not os.path.exists(certificado):
#             frappe.throw(f"Certificate not found: {certificado}")
#         if not os.path.exists(clave_privada):
#             frappe.throw(f"Private key not found: {clave_privada}")

#         wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
#         dt_now = datetime.datetime.utcnow()

#         # ----- XML CREATION -----
#         root = ET.Element("loginTicketRequest")
#         header = ET.SubElement(root, "header")
#         unique_id = ET.SubElement(header, "uniqueId")
#         generation_time = ET.SubElement(header, "generationTime")
#         expiration_time = ET.SubElement(header, "expirationTime")
#         service = ET.SubElement(root, "service")

#         generation_time.text = dt_now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         unique_id.text = dt_now.strftime("%y%m%d%H%M")
#         service.text = servicio_id
        
#         seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
#         out_xml = f"{seq_nr}-LoginTicketRequest.xml"
#         out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
#         out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"

#         try:
#             # Write XML file
            
#             xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
#             with open(out_xml, 'w', encoding='utf-8') as f:
#                 f.write(xml_content)

#             # Sign CMS
#             subprocess.run([
#                 'openssl', 'smime', '-sign',
#                 '-in', out_xml,
#                 '-signer', certificado,
#                 '-inkey', clave_privada,
#                 '-nodetach',
#                 '-outform', 'der',
#                 '-out', out_cms_der
#             ], check=True)
            
#             # Base64 encode
#             subprocess.run([
#                 'openssl', 'base64',
#                 '-in', out_cms_der,
#                 '-e',
#                 '-out', out_cms_der_b64
#             ], check=True)

#             with open(out_cms_der_b64, 'r') as f:
#                 cms = f.read()
#             print("under try catch section")
#             # WSAA LoginCms
#             client = Client(wsaa_wsdl)
#             wsaa_response = client.service.loginCms(cms)
            
#             # Parse WSAA response
#             response_root = ET.fromstring(wsaa_response)
#             token = response_root.find('.//credentials/token').text
#             sign = response_root.find('.//credentials/sign').text
#             # print(str(token))
#             print(str(row))
#             # Save token in row
#             row.token = token
#             row.sign = sign
#             settings.save()
#             frappe.db.commit()

#             frappe.msgprint(f"New token generated for row {row.name}")
#             return {"success": True, "token": token, "sign": sign}

#         except Exception as e:
#             frappe.log_error(f"AFIP Token Error: {str(e)}")
#             frappe.msgprint(f"Error generating token: {str(e)}")

#         finally:
#             # Cleanup
#             for file in [out_xml, out_cms_der, out_cms_der_b64]:
#                 if os.path.exists(file):
#                     os.remove(file)

#     except Exception as e:
#         frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
#         frappe.throw(f"Error in AFIP token generation: {str(e)}")

    

# def renew_all_afip_tokens():
#     settings = frappe.get_doc("AFIP Setting")

#     for row in settings.credentials:
#         try:
#             get_afip_token_scheduler(row)
#         except Exception as e:
#             frappe.log_error(f"AFIP Token renewal failed for row {row.name}: {str(e)}")

# ---------------------------


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

        # Get the expiration time from the token
        token_bytes = row.token.encode("utf-8")
        token_xml = ET.fromstring(token_bytes)
        expiration_time = token_xml.find(".//exp_time") 

        if expiration_time is not None:
            expiration_time = datetime.datetime.fromtimestamp(int(expiration_time.text))
            current_time = datetime.datetime.now()

            # Return True if token is still valid (considering a small buffer)
            return current_time < (expiration_time - datetime.timedelta(minutes=10))

        return False
    except Exception:
        return False
    
    
#Old and Correct Code

def get_afip_token(row_name):
    # frappe.throw("hello")
    try:
        # settings = frappe.get_doc("AFIP Setting")
        # for r in settings.:
        #     print(r)
        print(row)
        # Find the child row    
        row = next((r for r in settings.credentials if r.name == row_name), None)
        if not row:
            frappe.throw("Credentials row not found")
        
        # 1) USE VALID TOKEN
        if check_token_validity(row):
            frappe.msgprint(f"Using existing valid token for row {row_name}")
            return {"success": True, "token": row.token, "sign": row.sign}

        # 2) GENERATE NEW TOKEN
        site_path = frappe.get_site_path()
        
        # Set the service ID (replace with your actual service ID)
        servicio_id = "wsfe"
        
        certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
        clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')
        
        if not os.path.exists(certificado):
            frappe.throw(f"Certificate not found: {certificado}")
        if not os.path.exists(clave_privada):
            frappe.throw(f"Private key not found: {clave_privada}")

        wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
        servicio_id = "wsfe"
        dt_now = datetime.datetime.utcnow()

        # XML creation
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
        
        print(str(generation_time.text))
        print(str(expiration_time.text))
        print(str(unique_id.text))
        print(str(service.text))
        print(str(service))

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
            print(client)
            wsaa_response = client.service.loginCms(cms)
            
            # Parse response and update settings
            response_root = ET.fromstring(wsaa_response)
            print(response_root)
            token = response_root.find('.//credentials/token').text
            sign = response_root.find('.//credentials/sign').text
            expiration = response_root.find('.//credentials/expirationTime').text 
            expiration_dt = datetime.datetime.strptime(expiration, "%Y-%m-%dT%H:%M:%S.%fZ")
            
            # SAVE IN ROW ONLY
            row.token = token
            row.sign = sign
            row.expiration_time = expiration_dt 
            # frappe.throw(str(row.token))
            settings.save()
            frappe.db.commit()
            

            frappe.msgprint(f"New token generated for row {row_name}")
            return {"success": True, "token": token, "sign": sign}

        except Exception as e:
            frappe.log_error(f"AFIP Token Error: {str(e)}")
            frappe.msgprint(f"Error generating token: {str(e)}")

        finally:
                # Cleanup temporary files
                for file in [out_xml, out_cms_der, out_cms_der_b64]:
                    if os.path.exists(file):
                        os.remove(file)
                        
    except Exception as e:
        frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
        frappe.throw(f"Error in AFIP token generation: {str(e)}")
        

 

    

    
    
# def get_afip_token(row):
#     """
#     Generate or reuse AFIP WSAA token for a given credentials row.
#     Saves token, sign, and expiration_time in the row.
#     Returns JSON-like dict.
#     """
#     try:
#         settings = frappe.get_doc("AFIP Setting")
#         if not row:
#             frappe.throw("Credentials row not found")

#         # 1) USE EXISTING VALID TOKEN
#         if check_token_validity(row):
#         # Ensure row.expiration_time is set in DB if missing
#             frappe.throw("hello")
#             if not row.expiration_time:
#                 exp_dt = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
#                 frappe.db.set_value("Credentials", row.name, "expiration_time", exp_dt)
#                 frappe.db.commit()
#                 row.expiration_time = exp_dt  # update local object too

#             return {
#                 "success": True,
#                 "token": row.token,
#                 "sign": row.sign,
#                 "expiration_time": row.expiration_time.strftime("%Y-%m-%d %H:%M:%S")
#             }


#         # 2) GENERATE NEW TOKEN
#         site_path = frappe.get_site_path()
#         certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
#         clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')

#         if not os.path.exists(certificado) or not os.path.exists(clave_privada):
#             frappe.throw("Certificate or private key not found!")

#         wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
#         dt_now = datetime.datetime.utcnow()

#         # XML creation
#         root = ET.Element("loginTicketRequest")
#         header = ET.SubElement(root, "header")
#         unique_id = ET.SubElement(header, "uniqueId")
#         generation_time = ET.SubElement(header, "generationTime")
#         expiration_time_xml = ET.SubElement(header, "expirationTime")
#         service = ET.SubElement(root, "service")

#         generation_time.text = dt_now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         expiration_time_xml.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         unique_id.text = dt_now.strftime("%y%m%d%H%M")
#         service.text = "wsfe"

#         seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
#         out_xml = f"{seq_nr}-LoginTicketRequest.xml"
#         out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
#         out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"

#         try:
#             xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
#             with open(out_xml, 'w', encoding='utf-8') as f:
#                 f.write(xml_content)

#             subprocess.run([
#                 'openssl', 'smime', '-sign',
#                 '-in', out_xml,
#                 '-signer', certificado,
#                 '-inkey', clave_privada,
#                 '-nodetach',
#                 '-outform', 'der',
#                 '-out', out_cms_der
#             ], check=True)

#             subprocess.run([
#                 'openssl', 'base64',
#                 '-in', out_cms_der,
#                 '-e',
#                 '-out', out_cms_der_b64
#             ], check=True)

#             with open(out_cms_der_b64, 'r') as f:
#                 cms = f.read()

#             # Call WSAA
#             client = Client(wsaa_wsdl)
#             wsaa_response = client.service.loginCms(cms)

#             # Parse response
#             response_root = ET.fromstring(wsaa_response)
#             token = response_root.find('.//credentials/token').text
#             sign = response_root.find('.//credentials/sign').text
#             expiration_time_str = response_root.find('.//header/expirationTime').text
#             expiration_time_dt = datetime.datetime.fromisoformat(expiration_time_str.replace("Z", "+00:00"))

#             # Save in row (JSON-friendly)
#             frappe.db.set_value("Credentials", row.name, "token", token)
#             frappe.db.set_value("Credentials", row.name, "sign", sign)
#             frappe.db.set_value("Credentials", row.name, "expiration_time", expiration_time_dt)
#             frappe.db.commit()

#             return {
#                 "success": True,
#                 "token": token,
#                 "sign": sign,
#                 "expiration_time": expiration_time_dt.strftime("%Y-%m-%d %H:%M:%S")
#             }

#         finally:
#             for file in [out_xml, out_cms_der, out_cms_der_b64]:
#                 if os.path.exists(file):
#                     os.remove(file)

#     except Exception as e:
#         # Ignore AFIP "already has valid TA" error, reuse existing token
#         if "ya posee un TA valido" in str(e):
#             frappe.msgprint("AFIP already has a valid token, using existing one")
#             if row.token and row.sign:
#                 return {
#                     "success": True,
#                     "token": row.token,
#                     "sign": row.sign,
#                     "expiration_time": (row.expiration_time or (datetime.datetime.utcnow() + datetime.timedelta(minutes=10))).strftime("%Y-%m-%d %H:%M:%S")
#                 }
#         frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
#         frappe.throw(f"Error in AFIP token generation: {str(e)}")



# def get_afip_token(row):
#     try:
#         # 1) USE VALID TOKEN
#         if check_token_validity(row):
#             frappe.msgprint(f"Using existing valid token for row {row.idx}")
#             # print(str(row.token))
#             # print(str(row.sighn))
#             # print("token validate sucessfully")
#             if not row.expiration_time:
#                 # Parse expiration_time from token
#                 token_bytes = row.token.encode("utf-8")
#                 token_xml = ET.fromstring(token_bytes)
#                 exp_time = token_xml.find(".//exp_time")
#                 if exp_time is not None:
#                     exp_dt = datetime.datetime.fromtimestamp(int(exp_time.text))
#                     frappe.throw(str(exp_time))
#                     frappe.db.set_value("Credentials", row.name, "expiration_time", exp_dt)

#             return {"success": True, "token": row.token, "sign": row.sign}

#             # return {"success": True, "token": row.token, "sign": row.sign}

#         # 2) GENERATE NEW TOKEN
#         site_path = frappe.get_site_path()
#         servicio_id = "wsfe"
        
#         certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
#         clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')

#         if not os.path.exists(certificado):
#             frappe.throw(f"Certificate not found: {certificado}")
#         if not os.path.exists(clave_privada):
#             frappe.throw(f"Private key not found: {clave_privada}")

#         wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
#         dt_now = datetime.datetime.utcnow()

#         # Create XML
#         root = ET.Element("loginTicketRequest")
#         header = ET.SubElement(root, "header")
#         unique_id = ET.SubElement(header, "uniqueId")
#         generation_time = ET.SubElement(header, "generationTime")
#         expiration_time = ET.SubElement(header, "expirationTime")
#         service = ET.SubElement(root, "service")

#         generation_time.text = dt_now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         unique_id.text = dt_now.strftime("%y%m%d%H%M")
#         service.text = servicio_id

#         seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
#         out_xml = f"{seq_nr}-LoginTicketRequest.xml"
#         out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
#         out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"
       
#         try:
#             # Write XML
            
#             xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
#             with open(out_xml, 'w', encoding='utf-8') as f:
#                 f.write(xml_content)

#             # Sign CMS
#             subprocess.run([
#                 'openssl', 'smime', '-sign',
#                 '-in', out_xml,
#                 '-signer', certificado,
#                 '-inkey', clave_privada,
#                 '-nodetach',
#                 '-outform', 'der',
#                 '-out', out_cms_der
#             ], check=True)

#             # Base64 encode
#             subprocess.run([
#                 'openssl', 'base64',
#                 '-in', out_cms_der,
#                 '-e',
#                 '-out', out_cms_der_b64
#             ], check=True)

#             with open(out_cms_der_b64, 'r') as f:
#                 cms = f.read()
            
#             # Call WSAA
#             client = Client(wsaa_wsdl)
#             wsaa_response = client.service.loginCms(cms)
            
#             # Parse token
#             response_root = ET.fromstring(wsaa_response)
#             token = response_root.find('.//credentials/token').text
#             sign = response_root.find('.//credentials/sign').text
#             # expiration_time_str = response_root.find('.//header/expirationTime').text  # AFIP gives this
            
#             # # Convert to Python datetime
#             # expiration_time_dt = datetime.datetime.strptime(expiration_time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
            
#             frappe.throw("hello")
#             # Save row safely (WITHOUT calling settings.save)
#             frappe.db.set_value("Credentials", row.name, "token", token)
#             frappe.db.set_value("Credentials", row.name, "sign", sign)
#             frappe.db.set_value("Credentials", row.name, "expiration_time", expiration_time_dt)

#             frappe.msgprint(f"New token generated for row {row.idx}")
#             return {"success": True, "token": token, "sign": sign}

#         except Exception as e:
#             frappe.log_error(f"AFIP Token Error: {str(e)}")
#             frappe.msgprint(f"Error generating token: {str(e)}")

#         finally:
#             for file in [out_xml, out_cms_der, out_cms_der_b64]:
#                 if os.path.exists(file):
#                     os.remove(file)

#     except Exception as e:
#         frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
#         frappe.throw(f"Error in AFIP token generation: {str(e)}")


@frappe.whitelist()
def renew_all_afip_tokens():
    settings = frappe.get_doc("AFIP Setting")
    print(settings.credentials)
    for row in settings.credentials:
        print(row)
        if not check_token_validity(row):
            frappe.logger().info(f"[AFIP Scheduler] Token expired. Regenerating for row {row.idx}")
            get_afip_token(row)
        else:
            frappe.logger().info(f"[AFIP Scheduler] Token valid for row {row.idx}")
            
#Old and Correct Code

# def get_afip_token(row_name):
#     # frappe.throw("hello")
#     try:
#         settings = frappe.get_doc("AFIP Setting")
        
#         # Find the child row
#         row = next((r for r in settings.credentials if r.name == row_name), None)
#         if not row:
#             frappe.throw("Credentials row not found")
        
#         # 1) USE VALID TOKEN
#         if check_token_validity(row):
#             frappe.msgprint(f"Using existing valid token for row {row_name}")
#             return {"success": True, "token": row.token, "sign": row.sign}

#         # 2) GENERATE NEW TOKEN
#         site_path = frappe.get_site_path()
        
#         # Set the service ID (replace with your actual service ID)
#         servicio_id = "wsfe"
        
#         certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
#         clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')
        
#         if not os.path.exists(certificado):
#             frappe.throw(f"Certificate not found: {certificado}")
#         if not os.path.exists(clave_privada):
#             frappe.throw(f"Private key not found: {clave_privada}")

#         wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
#         servicio_id = "wsfe"
#         dt_now = datetime.datetime.utcnow()

#         # XML creation
#         # Create XML structure
#         root = ET.Element("loginTicketRequest")
#         header = ET.SubElement(root, "header")
#         unique_id = ET.SubElement(header, "uniqueId")
#         generation_time = ET.SubElement(header, "generationTime")
#         expiration_time = ET.SubElement(header, "expirationTime")
#         service = ET.SubElement(root, "service")

#         generation_time.text = (dt_now).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         unique_id.text = dt_now.strftime("%y%m%d%H%M")
#         service.text = servicio_id

#         seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
#         out_xml = f"{seq_nr}-LoginTicketRequest.xml"
#         out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
#         out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"
        

#         # Sign CMS
#         try:
#             # Write XML to file
#             xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
#             with open(out_xml, 'w', encoding='utf-8') as f:
#                 f.write(xml_content)
            
#             # Sign CMS
#             subprocess.run([
#                 'openssl', 'smime', '-sign',
#                 '-in', out_xml,
#                 '-signer', certificado,
#                 '-inkey', clave_privada,
#                 '-nodetach',
#                 '-outform', 'der',
#                 '-out', out_cms_der
#             ], check=True)
            
#             # Encode in BASE64
#             subprocess.run([
#                 'openssl', 'base64',
#                 '-in', out_cms_der,
#                 '-e',
#                 '-out', out_cms_der_b64
#             ], check=True)
            
#             with open(out_cms_der_b64, 'r') as f:
#                 cms = f.read()
            
#             # Call WSAA
#             client = Client(wsaa_wsdl)
#             print(client)
#             wsaa_response = client.service.loginCms(cms)
            
#             # Parse response and update settings
#             response_root = ET.fromstring(wsaa_response)
#             token = response_root.find('.//credentials/token').text
#             sign = response_root.find('.//credentials/sign').text
#             print
#             # SAVE IN ROW ONLY
#             row.token = token
#             row.sign = sign
#             # frappe.throw(str(row.token))
#             settings.save()
#             frappe.db.commit()
            

#             frappe.msgprint(f"New token generated for row {row_name}")
#             return {"success": True, "token": token, "sign": sign}

#         except Exception as e:
#             frappe.log_error(f"AFIP Token Error: {str(e)}")
#             frappe.msgprint(f"Error generating token: {str(e)}")

#         finally:
#                 # Cleanup temporary files
#                 for file in [out_xml, out_cms_der, out_cms_der_b64]:
#                     if os.path.exists(file):
#                         os.remove(file)
                        
#     except Exception as e:
#         frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
#         frappe.throw(f"Error in AFIP token generation: {str(e)}")



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
    
    
    
# def get_afip_token(row):
#     # frappe.throw("hello")
#     try:
#         settings = frappe.get_doc("AFIP Setting")
        
#         # Find the child row
#         # row = next((r for r in settings.credentials if r.name == row_name), None)
#         if not row:
#             frappe.throw("Credentials row not found")
        
#         # 1) USE VALID TOKEN
#         if check_token_validity(row):
#             frappe.msgprint(f"Using existing valid token for row {row}")
#             return {"success": True, "token": row.token, "sign": row.sign,"row": row.as_dict()   }

#         # 2) GENERATE NEW TOKEN
#         site_path = frappe.get_site_path()
        
#         # Set the service ID (replace with your actual service ID)
#         servicio_id = "wsfe"
        
#         certificado = os.path.join(site_path, 'private', 'files', 'finbyzCerficate.crt')
#         clave_privada = os.path.join(site_path, 'private', 'files', 'finbyz_key.key')
        
#         if not os.path.exists(certificado):
#             frappe.throw(f"Certificate not found: {certificado}")
#         if not os.path.exists(clave_privada):
#             frappe.throw(f"Private key not found: {clave_privada}")

#         wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
#         servicio_id = "wsfe"
#         dt_now = datetime.datetime.utcnow()

#         # XML creation
#         # Create XML structure
#         root = ET.Element("loginTicketRequest")
#         header = ET.SubElement(root, "header")
#         unique_id = ET.SubElement(header, "uniqueId")
#         generation_time = ET.SubElement(header, "generationTime")
#         expiration_time = ET.SubElement(header, "expirationTime")
#         service = ET.SubElement(root, "service")

#         generation_time.text = (dt_now).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
#         unique_id.text = dt_now.strftime("%y%m%d%H%M")
#         service.text = servicio_id

#         seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
#         out_xml = f"{seq_nr}-LoginTicketRequest.xml"
#         out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
#         out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"
        
        
#         # token_bytes = row.token.encode('utf-8')
#         # token_xml = ET.fromstring(token_bytes)
#         # expiration_time = token_xml.find('.//exp_time')
#         # expiration_time = datetime.datetime.fromtimestamp(int(expiration_time.text))
        

#         # Sign CMS
#         try:
#             # Write XML to file
#             xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
#             with open(out_xml, 'w', encoding='utf-8') as f:
#                 f.write(xml_content)
            
#             # Sign CMS
#             subprocess.run([
#                 'openssl', 'smime', '-sign',
#                 '-in', out_xml,
#                 '-signer', certificado,
#                 '-inkey', clave_privada,
#                 '-nodetach',
#                 '-outform', 'der',
#                 '-out', out_cms_der
#             ], check=True)
            
#             # Encode in BASE64
#             subprocess.run([
#                 'openssl', 'base64',
#                 '-in', out_cms_der,
#                 '-e',
#                 '-out', out_cms_der_b64
#             ], check=True)
            
#             with open(out_cms_der_b64, 'r') as f:
#                 cms = f.read()
            
#             # Call WSAA
#             client = Client(wsaa_wsdl)
#             print(client)
#             wsaa_response = client.service.loginCms(cms)
#             # Parse response and update settings
#             response_root = ET.fromstring(wsaa_response)
#             token = response_root.find('.//credentials/token').text
#             sign = response_root.find('.//credentials/sign').text
#             exp = response_root.find('.//header/expirationTime').text
#             expiration_time = parser.isoparse(exp)
#             expiration_time = expiration_time.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            
#             # exp_time_for_log = expiration_time 
#             # SAVE IN ROW ONLY
#             row.token = token
#             row.sign = sign
#             row.expiration_time = expiration_time
#             # frappe.throw(str(row.token))
#             row.db_update()
            

#             frappe.msgprint(f"New token generated for row {row}")
#             return {"success": True, "token": token, "sign": sign}

#         except Exception as e:
#             frappe.log_error(
#                 f"AFIP Token Generation Error: {str(e)}")
#             frappe.msgprint(
              
#                 f"Error in AFIP token generation: {str(e)}\n\n"
#                 f"Stored Expiration: {row.expiration_time or 'Not Set'}"
#             )
#         finally:
#                 # Cleanup temporary files
#                 for file in [out_xml, out_cms_der, out_cms_der_b64]:
#                     if os.path.exists(file):
#                         os.remove(file)
                        
#     except Exception as e:

#         # frappe.throw(wsaa_response)
#         frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
#         frappe.throw(f"Error in AFIP token generation: {str(e)}")
#         return {"success": False, "message": str(e)}





