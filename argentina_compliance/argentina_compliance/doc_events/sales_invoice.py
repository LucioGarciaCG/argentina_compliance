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
        if afip_details.use_sandbox_environment:
            wsdl = 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL'
        else:
            wsdl = 'https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL'
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
    """
    Map ERPNext invoice types to AFIP types
    
    Args:
        sales_invoice: Sales Invoice document
        
    Returns:
        int: AFIP invoice type code
            1: Factura A (Registered Responsible)
            6: Factura B (Final Consumer, Exempt)
            11: Factura C (Monotributo)
            Default is 1 if status not found
    """
    mapping = {
        "Final Consumer": 6,
        "Exempt": 6,
        "Monotributo Manager": 11,
        "Registered Responsible": 1,
        "Uncategorized": 1
    }
    
    # Get customer VAT status from custom field
    vat_status = frappe.get_value(
        "Customer", 
        sales_invoice.customer, 
        "custom_vat_status"
    )
    
    # Return mapped invoice type or default to 1 if status not found
    return mapping.get(vat_status, 1)

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
def cancel_invoice(salesInvoice):
    """
    Cancel an AFIP invoice by generating a credit note (Nota de Crédito)
    
    Args:
        salesInvoice (str): The name/ID of the Sales Invoice to cancel
    """
    try:
        # Get AFIP settings
        afip_details = frappe.get_doc("AFIP Setting")
        if not all([afip_details.token, afip_details.sign, afip_details.cuit]):
            frappe.throw("Missing AFIP credentials. Please check AFIP Settings.")

        # Initialize WSFE client
        if afip_details.use_sandbox_environment:
            wsdl = 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL'
        else:
            wsdl = 'https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL'
        client = zeep.Client(wsdl=wsdl)

        # Create authentication header
        auth = {
            'Token': afip_details.token.strip(),
            'Sign': afip_details.sign.strip(),
            'Cuit': int(afip_details.cuit)
        }

        # Get sales invoice details
        sales_invoice = frappe.get_doc("Sales Invoice", salesInvoice)
        customer = frappe.get_doc("Customer", sales_invoice.customer)

        # Detailed logging of invoice state
        invoice_details = {
            "invoice_name": salesInvoice,
            "invoice_doctype": sales_invoice.doctype,
            "docstatus": sales_invoice.docstatus,
            "posting_date": str(sales_invoice.posting_date),
            "grand_total": str(sales_invoice.grand_total),
            "custom_fields": {
                "custom_cae": getattr(sales_invoice, 'custom_cae', None),
                "custom_caefchvto": getattr(sales_invoice, 'custom_caefchvto', None),
                "custom_invoice_canceled": getattr(sales_invoice, 'custom_invoice_canceled', False),
                "custom_credit_note_number": getattr(sales_invoice, 'custom_credit_note_number', None),
                "custom_credit_note_cae": getattr(sales_invoice, 'custom_credit_note_cae', None)
            },
            "customer_details": {
                "customer_name": sales_invoice.customer,
                "tax_id": getattr(customer, 'tax_id', None),
                "custom_customer_document_types": getattr(customer, 'custom_customer_document_types', None)
            },
            "all_custom_fields": {
                key: getattr(sales_invoice, key, None) 
                for key in dir(sales_invoice) 
                if key.startswith('custom_')
            }
        }
        
        frappe.log_error(
            message=f"Detailed invoice state during cancellation attempt:\n{json.dumps(invoice_details, indent=2)}",
            title="AFIP Invoice Cancellation - Detailed Status"
        )
        
        # Check if already cancelled in AFIP
        if getattr(sales_invoice, 'custom_invoice_canceled', False):
            frappe.log_error(
                message=f"Cancellation attempted on already cancelled invoice:\n{json.dumps(invoice_details, indent=2)}",
                title="AFIP Invoice Already Cancelled"
            )
            frappe.throw("This invoice has already been cancelled in AFIP.")

        # Verify that the invoice has a CAE
        if not getattr(sales_invoice, 'custom_cae', None):
            frappe.log_error(
                message=f"Cancellation attempted without CAE:\n{json.dumps(invoice_details, indent=2)}",
                title="AFIP Missing CAE"
            )
            frappe.throw(
                msg="This invoice has not been authorized by AFIP yet. "
                    "Please ensure the invoice has a valid CAE before cancellation.",
                title="AFIP Authorization Required"
            )

        # Get POS number and determine credit note type
        pos_number = int(sales_invoice.pos_profile) if sales_invoice.pos_profile else 1
        original_invoice_type = get_invoice_type(sales_invoice)
        
        # Map invoice types to credit note types
        credit_note_type_mapping = {
            1: 3,   # Factura A -> Nota de Crédito A
            6: 8,   # Factura B -> Nota de Crédito B
            11: 13  # Factura C -> Nota de Crédito C
        }
        credit_note_type = credit_note_type_mapping.get(original_invoice_type)
        
        if not credit_note_type:
            frappe.throw(f"Unsupported invoice type for credit note: {original_invoice_type}")

        # Get last authorized credit note number
        last_credit_note = get_last_authorized_invoice(client, auth, pos_number, credit_note_type)
        next_credit_note_number = last_credit_note + 1

        # Calculate amounts - ensure positive values for credit note
        total_amount = abs(float(sales_invoice.grand_total))
        net_amount = abs(float(sales_invoice.net_total))
        vat_amount = abs(float(sales_invoice.total_taxes_and_charges))

        # Get VAT rate from invoice and ensure it's positive
        vat_rate = 21.0  # Default VAT rate
        if sales_invoice.taxes:
            for tax in sales_invoice.taxes:
                if tax.rate > 0:
                    vat_rate = abs(tax.rate)
                    break

        # Log the amounts being used
        frappe.log_error(
            message=f"Credit Note Amounts:\n"
                    f"Total Amount: {total_amount}\n"
                    f"Net Amount: {net_amount}\n"
                    f"VAT Amount: {vat_amount}\n"
                    f"VAT Rate: {vat_rate}",
            title="AFIP Credit Note - Amount Calculations"
        )

        # Create request data structure
        CbteAsoc = client.get_type('ns0:CbteAsoc')
        ArrayOfCbteAsoc = client.get_type('ns0:ArrayOfCbteAsoc')
        AlicIva = client.get_type('ns0:AlicIva')
        ArrayOfAlicIva = client.get_type('ns0:ArrayOfAlicIva')

        # Create associated invoice array
        cbte_asoc = CbteAsoc(
            Tipo=original_invoice_type,
            PtoVta=pos_number,
            Nro=extract_invoice_number(sales_invoice.name)
        )
        cbtes_asoc_array = ArrayOfCbteAsoc([cbte_asoc])

        # Create IVA array - ensure positive values
        alic_iva = AlicIva(
            Id=get_vat_rate_id(vat_rate),
            BaseImp=round(abs(net_amount), 2),  # Ensure positive base amount
            Importe=round(abs(vat_amount), 2)   # Ensure positive VAT amount
        )
        array_alic_iva = ArrayOfAlicIva([alic_iva])

        # Create FECAEDetRequest - ensure all amounts are positive
        fecae_det_request = {
            'Concepto': 1,  # Products
            'DocTipo': get_doc_type(customer),
            'DocNro': int(customer.tax_id) if customer.tax_id else 0,
            'CbteDesde': next_credit_note_number,
            'CbteHasta': next_credit_note_number,
            'CbteFch': datetime.now().strftime('%Y%m%d'),
            'ImpTotal': round(abs(total_amount), 2),
            'ImpTotConc': 0.0,
            'ImpNeto': round(abs(net_amount), 2),
            'ImpOpEx': 0.0,
            'ImpIVA': round(abs(vat_amount), 2),
            'ImpTrib': 0.0,
            'MonId': 'PES',
            'MonCotiz': 1.0,
            'CbtesAsoc': cbtes_asoc_array,
            'Iva': array_alic_iva
        }

        # Create full request structure
        request_data = {
            'Auth': auth,
            'FeCAEReq': {
                'FeCabReq': {
                    'CantReg': 1,
                    'PtoVta': pos_number,
                    'CbteTipo': credit_note_type
                },
                'FeDetReq': {
                    'FECAEDetRequest': [fecae_det_request]
                }
            }
        }

        # Log request data for debugging
        frappe.log_error(
            message=f"AFIP Credit Note Request Data:\n{json.dumps(request_data, indent=2, default=str)}",
            title="AFIP Debug - Credit Note Request"
        )

        try:
            # Request CAE for credit note
            response = client.service.FECAESolicitar(**request_data)
            
            # Log raw response for debugging
            frappe.log_error(
                message=f"AFIP Raw Response: {response}",
                title="AFIP Debug - Credit Note Response"
            )

            # Check if response has Errors
            if hasattr(response, 'Errors') and response.Errors:
                error_msg = format_afip_errors(response.Errors)
                frappe.throw(f"AFIP Error Response: {error_msg}")

            # Process response
            if (hasattr(response, 'FeDetResp') and 
                hasattr(response.FeDetResp, 'FECAEDetResponse')):
                
                det_resp = response.FeDetResp.FECAEDetResponse[0]
                
                # Log any observations
                if hasattr(det_resp, 'Observaciones'):
                    obs = det_resp.Observaciones.Obs 
                    if isinstance(obs, list):
                        obs_msg = "; ".join([
                            f"Warning {o.Code}: {o.Msg}" 
                            for o in obs
                        ])
                    else:
                        obs_msg = f"Warning {obs.Code}: {obs.Msg}"
                    frappe.msgprint(f"AFIP Warnings: {obs_msg}", indicator='orange')

                # Check resultado and get CAE for credit note
                if det_resp.Resultado == 'A' and det_resp.CAE:
                    credit_note_cae = det_resp.CAE
                    credit_note_cae_vto = det_resp.CAEFchVto
                    
                    # Generate QR code for credit note
                    qr_base64 = generate_qr_code(sales_invoice, credit_note_cae, credit_note_cae_vto)

                    # Mark original invoice as cancelled
                    frappe.db.set_value("Sales Invoice", salesInvoice, {
                        # "custom_invoice_canceled": 1,
                        # "custom_credit_note_number": next_credit_note_number,
                        "custom_cae": credit_note_cae,
                        "custom_caefchvto": credit_note_cae_vto,
                        "custom_qr_base64": qr_base64
                    })
                    frappe.db.commit()
                    
                    frappe.msgprint(f"Credit note generated successfully with CAE: {credit_note_cae}")
                    return {
                        "success": True,
                        "credit_note_number": next_credit_note_number,
                        "cae": credit_note_cae,
                        "cae_vto": credit_note_cae_vto
                    }
                else:
                    error_msg = "AFIP Validation Error"
                    if hasattr(det_resp, 'Observaciones'):
                        obs = det_resp.Observaciones.Obs
                        if isinstance(obs, list):
                            error_msg += ": " + "; ".join([f"{o.Code}: {o.Msg}" for o in obs])
                        else:
                            error_msg += f": {obs.Code}: {obs.Msg}"
                    frappe.throw(error_msg)
            else:
                frappe.throw("Invalid response structure from AFIP")

        except zeep.exceptions.Fault as e:
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
            error_msg = f"AFIP Credit Note Error - Details: {json.dumps(detailed_error, indent=2)}"
        
        frappe.log_error(
            message=f"AFIP Credit Note Generation Error:\n{error_msg}\n\nTraceback:\n{traceback.format_exc()}",
            title="AFIP Credit Note Error - Detailed"
        )
        
        frappe.throw(
            msg=f"Error generating credit note: {error_msg}. Please check error logs for details.",
            title="AFIP Credit Note Error"
        )    