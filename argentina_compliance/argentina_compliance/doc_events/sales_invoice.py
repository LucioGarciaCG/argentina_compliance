import frappe
import zeep
from datetime import datetime
import base64
import json
from zeep.exceptions import Fault
import traceback


def extract_invoice_number(sales_invoice_name):
    """
    Safely extracts invoice number from sales invoice name
    handling 2, 3, or 4 digit numbers
    """
    try:
        # Split by hyphen and get the last part
        number_part = sales_invoice_name.split('-')[-1]
        # Remove any leading zeros and convert to int
        clean_number = int(number_part.lstrip('0'))
        return clean_number
    except (ValueError, IndexError) as e:
        frappe.throw(f"Invalid invoice number format: {sales_invoice_name}")

def get_last_authorized_invoice(client, auth, pos_number, invoice_type):
    """
    Get the last authorized invoice number from AFIP
    """
    try:
        response = client.service.FECompUltimoAutorizado(auth, pos_number, invoice_type)
        if hasattr(response, 'Errors') and response.Errors:
            error_msg = format_afip_errors(response.Errors)
            frappe.throw(f"AFIP Error: {error_msg}")
        return response.CbteNro
    except Exception as e:
        frappe.throw(f"Error getting last authorized invoice: {str(e)}")

@frappe.whitelist()
def generate_invoice(salesInvoice):
    try:
        # Get AFIP settings
        afip_details = frappe.get_doc("AFIP Setting")
        if not all([afip_details.token, afip_details.sign, afip_details.cuit]):
            frappe.throw("Missing AFIP credentials. Please check AFIP Settings.")

        # Initialize WSFE client
        wsdl = 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL'
        client = zeep.Client(wsdl=wsdl)

        # Prepare authentication data
        auth = {
            'Token': afip_details.token.strip(),
            'Sign': afip_details.sign.strip(),
            'Cuit': int(afip_details.cuit)
        }

        # Get sales invoice details
        sales_invoice = frappe.get_doc("Sales Invoice", salesInvoice)
        customer = frappe.get_doc("Customer", sales_invoice.customer)
        
        # Get POS number and invoice type
        pos_number = int(sales_invoice.pos_profile) if sales_invoice.pos_profile else 1
        invoice_type = get_invoice_type(sales_invoice)

        # Validate invoice number sequence
        last_invoice = get_last_authorized_invoice(client, auth, pos_number, invoice_type)
        current_number = extract_invoice_number(sales_invoice.name)
        
        if current_number != last_invoice + 1:
            frappe.throw(
                f"Invalid invoice number sequence. Expected {last_invoice + 1}, got {current_number}. "
                "Please check the last authorized invoice in AFIP."
            )

        # Calculate VAT
        vat_tax = 0
        for tax in sales_invoice.taxes:
            if tax.rate > 0:
                vat_tax = tax.rate
                break

        # Get current date in AFIP format
        formatted_date = sales_invoice.posting_date.strftime('%Y%m%d')

        # Calculate amounts
        total_amount = float(sales_invoice.grand_total)
        net_amount = float(sales_invoice.net_total)
        vat_amount = float(sales_invoice.total_taxes_and_charges)

        # Prepare invoice data
        invoice = {
            'FeCabReq': {
                'CantReg': 1,
                'PtoVta': pos_number,
                'CbteTipo': invoice_type
            },
            'FeDetReq': {
                'FECAEDetRequest': [{
                    'Concepto': 1,
                    'DocTipo': get_doc_type(customer),
                    'DocNro': int(customer.tax_id) if customer.tax_id else 0,
                    'CbteDesde': current_number,
                    'CbteHasta': current_number,
                    'CbteFch': formatted_date,
                    'ImpTotal': round(total_amount, 2),
                    'ImpTotConc': 0.0,
                    'ImpNeto': round(net_amount, 2),
                    'ImpOpEx': 0.0,
                    'ImpIVA': round(vat_amount, 2),
                    'ImpTrib': 0.0,
                    'MonId': 'PES',
                    'MonCotiz': 1.0,
                    'Iva': {
                        'AlicIva': [{
                            'Id': get_vat_rate_id(vat_tax),
                            'BaseImp': round(net_amount, 2),
                            'Importe': round(vat_amount, 2)
                        }]
                    }
                }]
            }
        }

        # Log request data for debugging
        frappe.log_error(
            message=f"AFIP Request Data:\nAuth: {auth}\nInvoice: {invoice}",
            title="AFIP Debug - Request"
        )

        try:
            # Add transport logging
            import logging.config
            logging.config.dictConfig({
                'version': 1,
                'formatters': {
                    'verbose': {
                        'format': '%(name)s: %(message)s'
                    }
                },
                'handlers': {
                    'console': {
                        'level': 'DEBUG',
                        'class': 'logging.StreamHandler',
                        'formatter': 'verbose',
                    },
                },
                'loggers': {
                    'zeep.transports': {
                        'level': 'DEBUG',
                        'propagate': True,
                        'handlers': ['console'],
                    },
                }
            })

            # Pre-request validation
            frappe.log_error(
                message=f"Pre-request validation:\nToken length: {len(auth['Token'])}\nSign length: {len(auth['Sign'])}\nCUIT: {auth['Cuit']}",
                title="AFIP Debug - Pre-request"
            )
            
            response = client.service.FECAESolicitar(auth, invoice)
            
            # Log raw response for debugging
            frappe.log_error(
                message=f"AFIP Raw Response: {response}",
                title="AFIP Debug - Response"
            )
            
            # Check if response has Errors
            if hasattr(response, 'Errors') and response.Errors:
                error_msg = format_afip_errors(response.Errors)
                frappe.throw(f"AFIP Error Response: {error_msg}")

            # Check for FeDetResp structure correctly
            if (hasattr(response, 'FeDetResp') and 
                hasattr(response.FeDetResp, 'FECAEDetResponse') and 
                response.FeDetResp.FECAEDetResponse):
                
                det_resp = response.FeDetResp.FECAEDetResponse[0]
                
                # Log any observations
                if hasattr(det_resp, 'Observaciones') and det_resp.Observaciones:
                    obs_msg = "; ".join([
                        f"Warning {obs.Code}: {obs.Msg}" 
                        for obs in det_resp.Observaciones.Obs
                    ])
                    frappe.msgprint(f"AFIP Warnings: {obs_msg}", indicator='orange')

                # Check resultado and get CAE
                if det_resp.Resultado == 'A' and hasattr(det_resp, 'CAE'):
                    cae = det_resp.CAE
                    cae_vto = det_resp.CAEFchVto
                    
                    # Generate QR code
                    qr_base64 = generate_qr_code(sales_invoice, cae, cae_vto)

                    # Update Sales Invoice
                    frappe.db.set_value("Sales Invoice", salesInvoice, {
                        "custom_cae": cae,
                        "custom_caefchvto": cae_vto,
                        "custom_qr_base64": qr_base64
                    })
                    frappe.db.commit()
                    
                    frappe.msgprint(f"Invoice registered successfully with CAE: {cae}")
                    return {"success": True, "cae": cae, "cae_vto": cae_vto}
                else:
                    frappe.throw(f"AFIP Validation Error: {det_resp.Resultado}")
            else:
                frappe.throw("Invalid response structure from AFIP")

        except Fault as e:
            frappe.throw(f"AFIP Web Service Error: {str(e)}")
            
    except Exception as e:
        error_msg = str(e)
        if not error_msg or error_msg == "0":
            # Get more detailed error information
            detailed_error = {
                "error_type": type(e).__name__,
                "error_args": getattr(e, 'args', []),
                "error_message": str(e),
                "afip_details": {
                    "token_exists": bool(afip_details.token),
                    "sign_exists": bool(afip_details.sign),
                    "cuit_exists": bool(afip_details.cuit)
                }
            }
            error_msg = f"AFIP Webservice Error - Details: {json.dumps(detailed_error, indent=2)}"
        
        frappe.log_error(
            message=f"AFIP Invoice Generation Error:\n{error_msg}\n\nTraceback:\n{traceback.format_exc()}",
            title="AFIP Error - Detailed"
        )
        
        frappe.throw(
            msg=f"Error generating AFIP invoice: {error_msg}. Please check error logs for details.",
            title="AFIP Error"
        )

# Helper functions remain the same
def get_invoice_type(sales_invoice):
    """Map ERPNext invoice types to AFIP types"""
    mapping = {
        "A": 1,  # Factura A
        "B": 6,  # Factura B
        "C": 11  # Factura C
    }
    return mapping.get(sales_invoice.custom_type_of_invoice, 1)

def get_doc_type(customer):
    """Map customer document types to AFIP types"""
    mapping = {
        "CUIT": 80,
        "DNI": 96,
        "CI": 90
    }
    return mapping.get(customer.custom_customer_document_types, 80)

def get_vat_rate_id(rate):
    """Map VAT rates to AFIP IDs"""
    mapping = {
        21.0: 5,  # 21%
        10.5: 4,  # 10.5%
        27.0: 6   # 27%
    }
    return mapping.get(rate, 5)

def format_afip_errors(errors):
    """Format AFIP error messages with more detailed handling"""
    try:
        if hasattr(errors, 'Err'):
            if isinstance(errors.Err, (list, tuple)):
                return "; ".join([f"Error {err.Code}: {err.Msg}" for err in errors.Err])
            else:
                return f"Error {errors.Err.Code}: {errors.Err.Msg}"
        elif isinstance(errors, (list, tuple)):
            return "; ".join([f"Error {err.Code if hasattr(err, 'Code') else 'Unknown'}: {err.Msg if hasattr(err, 'Msg') else str(err)}" for err in errors])
        else:
            error_dict = {
                'raw_error': str(errors),
                'error_type': type(errors).__name__,
                'has_err': hasattr(errors, 'Err'),
                'error_dir': dir(errors)
            }
            return f"Unstructured Error: {json.dumps(error_dict, indent=2)}"
    except Exception as e:
        return f"Error while formatting AFIP errors: {str(e)}, Raw errors: {str(errors)}"

def get_company_cuit():
    """Fetch CUIT from AFIP Settings
    
    Returns:
        str: Company CUIT number or None if not found
    """
    try:
        afip_settings = frappe.get_single("AFIP Setting")
        if not afip_settings.cuit:
            frappe.log_error(
                message="CUIT not configured in AFIP Settings",
                title="AFIP Configuration Error"
            )
            return None
        return afip_settings.cuit.replace("-", "").strip()
    except Exception as e:
        frappe.log_error(
            message=f"Error fetching CUIT from AFIP Settings: {str(e)}",
            title="AFIP Configuration Error"
        )
        return None

import json
import base64
import urllib.parse
import qrcode
from io import BytesIO

def generate_qr_code(invoice, cae, cae_vto):
    try:
        # Your existing data preparation code remains the same
        data = {
            "ver": 1,
            "fecha": invoice.posting_date.strftime("%Y-%m-%d"),
            "cuit": int(frappe.db.get_single_value("AFIP Setting", "cuit")),
            "ptoVta": int(invoice.pos_profile) if invoice.pos_profile else 1,
            "tipoCmp": get_invoice_type(invoice),
            "nroCmp": int(invoice.name.split('-')[-1]),
            "importe": float(invoice.grand_total),
            "moneda": "PES",
            "ctz": 1,
            "tipoDocRec": get_doc_type(frappe.get_doc("Customer", invoice.customer)),
            "nroDocRec": int(invoice.tax_id) if invoice.tax_id else 0,
            "tipoCodAut": "E",
            "codAut": int(cae)
        }

        # Convert data to JSON and create URL
        json_string = json.dumps(data)
        url_encoded = base64.b64encode(json_string.encode()).decode()
        afip_url = f'https://www.afip.gob.ar/fe/qr/?p={url_encoded}'

        # Create QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        
        # Add the URL to QR code
        qr.add_data(afip_url)
        qr.make(fit=True)

        # Create QR image
        qr_image = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffered = BytesIO()
        qr_image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Return with proper data URI prefix
        return f"data:image/png;base64,{img_str}"

    except Exception as e:
        frappe.log_error(
            message=f"QR Code generation error: {str(e)}",
            title="QR Code Error"
        )
        return None

@frappe.whitelist()
def cancel_invoice(self, method):
    """
    Cancel an already generated AFIP invoice
    
    Args:
        salesInvoice (str): The name/ID of the Sales Invoice document
        
    Returns:
        dict: Result of the cancellation operation
    """
    try:
        # Get AFIP settings
        afip_details = frappe.get_doc("AFIP Setting")
        if not all([afip_details.token, afip_details.sign, afip_details.cuit]):
            frappe.throw("Missing AFIP credentials. Please check AFIP Settings.")

        # Initialize WSFE client
        wsdl = 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL'
        client = zeep.Client(wsdl=wsdl)

        # Prepare authentication data
        auth = {
            'Token': afip_details.token.strip(),
            'Sign': afip_details.sign.strip(),
            'Cuit': int(afip_details.cuit)
        }

        # Get sales invoice details
        sales_invoice = frappe.get_doc("Sales Invoice", self.name)
        
        # Verify that the invoice has a CAE (meaning it was previously authorized)
        if not sales_invoice.custom_cae:
            frappe.throw("This invoice has not been authorized by AFIP yet.")

        # Get POS number and invoice type
        pos_number = int(sales_invoice.pos_profile) if sales_invoice.pos_profile else 1
        invoice_type = get_invoice_type(sales_invoice)
        current_number = extract_invoice_number(sales_invoice.name)

        # Prepare cancellation request
        cancel_data = {
            'FeDetReq': {
                'FECAEDetRequest': [{
                    'CbteDesde': current_number,
                    'CbteHasta': current_number,
                    'CbteTipo': invoice_type,
                    'PtoVta': pos_number
                }]
            }
        }

        # Log request data for debugging
        frappe.log_error(
            message=f"AFIP Cancellation Request Data:\nAuth: {auth}\nCancel Data: {cancel_data}",
            title="AFIP Debug - Cancellation Request"
        )

        try:
            # Call AFIP webservice to cancel the invoice
            response = client.service.CompConsultar(auth, cancel_data)
            
            # Log raw response for debugging
            frappe.log_error(
                message=f"AFIP Cancellation Raw Response: {response}",
                title="AFIP Debug - Cancellation Response"
            )

            # Check if response has Errors
            if hasattr(response, 'Errors') and response.Errors:
                error_msg = format_afip_errors(response.Errors)
                frappe.throw(f"AFIP Error Response: {error_msg}")

            # Check response status
            if hasattr(response, 'ResultGet') and response.ResultGet:
                result = response.ResultGet
                if result.Resultado == 'A':  # 'A' means accepted
                    # Update Sales Invoice
                    frappe.db.set_value("Sales Invoice", salesInvoice, {
                        "custom_cae": None,
                        "custom_caefchvto": None,
                        "custom_qr_base64": None,
                        "custom_invoice_canceled": 1
                    })
                    frappe.db.commit()
                    
                    frappe.msgprint("Invoice cancelled successfully in AFIP")
                    return {"success": True, "message": "Invoice cancelled successfully"}
                else:
                    frappe.throw(f"AFIP Cancellation Error: {result.Resultado}")
            else:
                frappe.throw("Invalid response structure from AFIP")

        except Fault as e:
            frappe.throw(f"AFIP Web Service Error: {str(e)}")
            
    except Exception as e:
        error_msg = str(e)
        if not error_msg or error_msg == "0":
            detailed_error = {
                "error_type": type(e).__name__,
                "error_args": getattr(e, 'args', []),
                "error_message": str(e),
                "afip_details": {
                    "token_exists": bool(afip_details.token),
                    "sign_exists": bool(afip_details.sign),
                    "cuit_exists": bool(afip_details.cuit)
                }
            }
            error_msg = f"AFIP Cancellation Error - Details: {json.dumps(detailed_error, indent=2)}"
        
        frappe.log_error(
            message=f"AFIP Invoice Cancellation Error:\n{error_msg}\n\nTraceback:\n{traceback.format_exc()}",
            title="AFIP Cancellation Error - Detailed"
        )
        
        frappe.throw(
            msg=f"Error cancelling AFIP invoice: {error_msg}. Please check error logs for details.",
            title="AFIP Cancellation Error"
        )

        