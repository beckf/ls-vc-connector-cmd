import veracross_api
import lightspeed_api
import sys
import getopt
import os
import datetime
import pandas
import csv
from decimal import Decimal, ROUND_HALF_UP
import logging
import json
import pytz
import datetime

__version__ = "0.2"

# Creating logger
applogs = logging.getLogger(__name__)
applogs.setLevel(logging.DEBUG)

# Stream Log
stream = logging.StreamHandler()
streamformat = logging.Formatter("%(levelname)s:%(module)s:%(message)s")
stream.setLevel(logging.DEBUG)
stream.setFormatter(streamformat)

# Adding all handlers to the logging
applogs.addHandler(stream)


def print_help():
    print(
        """
        main.py:
        --version = Script version
        --help = This text
        --operation = "sync" to performa sync with LS. "export" to export data from LS.       
        --config = Complete path to config file from LSVCConnector (see sample_config.json)
        --operation_json = Optional JSON file with sync parameters.
            Mix of JSON and other switches allowed.
            Other switches override JSON.
        --type = VC role to sync ("Students" or "Faculty Staff")
        --sync_force = Force update all VC records in LS.
        --sync_delete = Search all LS records and delete all not found in VC.
        --filter_after_date = Only update records updated in VC after date formatted as YYYY-MM-DD
        --filter_grade_level = Comma seperated list of grades by VC ID to sync ("1,2,3,4,20")
        --log_path = Complete file pathf to where the logfile should be.
        
        /usr/local/bin/python3 main.py --operation=sync --config=config.json --operation_json=/path/to/operation_json.json
        """
    )


def load_json(file):
    f = open(file)
    r = json.load(f)
    return r


def get_ls_customer_types(lightspeed_connection):
    ls_customer_types = dict()

    try:
        ct = lightspeed_connection.get("CustomerType")
        for i in ct['CustomerType']:
            ls_customer_types[i["name"]] = i["customerTypeID"]
    except:
        applogs.info("Cannot get customer types from Lightspeed API, or none exist.")
        sys.exit(2)

    return ls_customer_types


def get_custom_field_id(lightspeed_connection, name):
    """
    Get the Lightspeed id for the customfields
    :return:
    """
    try:
        custom_fields = lightspeed_connection.get("Customer/CustomField")
        if isinstance(custom_fields["CustomField"], list):
            for cf in custom_fields["CustomField"]:
                # Find internal id for named field
                if str(cf["name"]) == str(name):
                    return cf["customFieldID"]
        else:
            return None
    except:
        return None


def delete_customer(config):
    """
    Delete records in Lightspeed.  Filters customers to those that have a companyRegistrationNumber
    :return:
    """
    c = config
    ls = lightspeed_api.Lightspeed(c)
    vc = veracross_api.Veracross(c)

    valid_vc_ids = []
    for i in vc.pull("facstaff", parameters=dict(roles='1,2')):
        valid_vc_ids.append(i["person_pk"])
    for i in vc.pull("students", parameters=dict(option="2")):
        valid_vc_ids.append(i["person_pk"])

    current_customers = ls.get("Customer", dict(load_relations="all"))

    for i in current_customers["Customer"]:
        if i["companyRegistrationNumber"] != '':
            if int(i["companyRegistrationNumber"]) not in valid_vc_ids:
                if float(i["CreditAccount"]["balance"]) <= 0:
                    applogs.info("Deleting customer {} {}".format(i["firstName"], i["lastName"]))
                    ls.delete("Customer/" + i["customerID"])
                else:
                    applogs.info("Cannot delete customer {}, {} {} with credit balance.".format(i["customerID"],
                                                                                         i["firstName"],
                                                                                         i["lastName"]))


def sync_ls_vc(config, operation_json):

    c = config
    ls = lightspeed_api.Lightspeed(c)
    vc = veracross_api.Veracross(c)

    # Make sure we have a lastsync and veracross id field mapped.
    if c["import_options_veracrossid"] is None or c["import_options_lastsync"] is None:
        applogs.info("Missing import_options_veracrossid or import_options_lastsync in config file.")
        sys.exit(2)

    # Placeholder for parameters
    param = {}

    # Determine if we are syncing VC changes after particular date and update params set to VC.
    if "after_date" in operation_json["sync_filters"]:
        if operation_json["sync_filters"]["after_date"]:
            param.update({"updated_after": str(operation_json["sync_filters"]["after_date"])})

    # If we are working with students, add additional parameters.
    if "type" in operation_json:
        if operation_json["type"] == "Students":
            applogs.info("Getting Veracross Students (Current)")

            # Add a grade level filter
            if "grade_level" in operation_json["sync_filters"]:
                if isinstance(operation_json["sync_filters"]["grade_level"], list):
                    grade_list_string = ",".join(str(item) for item in operation_json["sync_filters"]["grade_level"])
                    param.update({"grade_level": str(grade_list_string)})

            # Limit to only current students
            param.update({"option": "2"})

            # Show our parameters to console
            applogs.info("VC Parameters: " + str(param))

            # Get Veracross data for students
            vcdata = vc.pull("students", parameters=param)

            # Get Lightspeed id number that matches customer_type Student
            try:
                ls_customer_types = get_ls_customer_types(ls)
                ls_customerTypeID = ls_customer_types["Student"]
            except:
                applogs.info("Unable to assign customer type from Lightspeed")
                sys.exit(2)

        # Determine if we want FacultyStaff from VC
        if operation_json["type"] == "Faculty Staff":

            applogs.info("Getting Veracross Faculty Staff (Faculty and Staff)")
            # Limit to roles 1 & 2 in VC Api.
            param.update({"roles": "1,2"})

            # Show parameters log
            applogs.info("VC Parameters: " + str(param))

            # Get Veracross data for Faculty Staff
            vcdata = vc.pull("facstaff", parameters=param)

            # Determine what Lightspeed customer id number for FacStaff
            try:
                ls_customer_types = get_ls_customer_types(ls)
                ls_customerTypeID = ls_customer_types["FacultyStaff"]
            except:
                applogs.info("Unable to assign customer type from Lightspeed")
                sys.exit(2)

    # User did not select a user type
    else:
        applogs.info("type of 'Faculty Staff' or 'Students' not found in sync options json file.")
        sys.exit(2)

    if vcdata:
        # Get field IDs
        vc_custom_id = get_custom_field_id(ls, str(c["import_options_veracrossid"]))
        lastsync_custom_id = get_custom_field_id(ls, str(c["import_options_lastsync"]))

        # Loop through the data from VC.
        for i in vcdata:

            applogs.info("Processing VC Record {}".format(i["person_pk"]))

            # Get household data for this person
            hh = vc.pull("households/" + str(i["household_fk"]))
            h = hh["household"]

            # Set search parameters for lightspeed and see if we find someone in LS.
            lsparam = dict(load_relations='all', limit=1, companyRegistrationNumber=str(i["person_pk"]))
            check_current = ls.get("Customer", parameters=lsparam)

            # Format data to how it should look. First name will format later.
            vc_formatted = {'Customer':
                                {'firstName': '',
                                 'lastName': i["last_name"],
                                 'companyRegistrationNumber': i["person_pk"],
                                 'customerTypeID': ls_customerTypeID,
                                 'Contact': {
                                     'custom': i["person_pk"],
                                     'noEmail': 'false',
                                     'noPhone': 'false',
                                     'noMail': 'false',
                                     'Emails': {
                                         'ContactEmail': {
                                             'address': i["email_1"],
                                             'useType': 'Primary'
                                         }
                                     },
                                     'Addresses': {
                                         'ContactAddress': {
                                             'address1': h["address_1"],
                                             'address2': h["address_2"],
                                             'city': h["city"],
                                             'state': h["state_province"],
                                             'zip': h["postal_code"],
                                             'country': h["country"],
                                             'countryCode': '',
                                             'stateCode': ''
                                         }
                                     }
                                 },
                                 'CreditAccount': {
                                     'creditLimit': str(c["import_options_creditamount"]) + '.00'
                                 },
                                 'CustomFieldValues': {
                                     'CustomFieldValue': [{
                                         'customFieldID': vc_custom_id,
                                         'value': str(i["person_pk"])
                                     }, {
                                         'customFieldID': lastsync_custom_id,
                                         'value': str(datetime.datetime.now())
                                     }
                                     ]}
                                 }
                            }

            # Update data to use correct nick name format from VC.
            # Added because of bug in VC API where sometimes one is returned over other.
            if 'nick_first_name' in i:
                vc_formatted['Customer']['firstName'] = i['nick_first_name']
            elif 'first_nick_name' in i:
                vc_formatted['Customer']['firstName'] = i['first_nick_name']

            # Did we find a record in Lighspeed to sync to?
            if check_current:

                # Create two dictionaries one for VC and the other for LS
                # We will see if they match later.
                vc_person = dict()
                ls_customer = dict()

                # Format VC Data for comparison
                vc_person["personpk"] = str(i["person_pk"])
                vc_person["last_name"] = i["last_name"]
                if 'nick_first_name' in i:
                    vc_person["first_name"] = i['nick_first_name']
                elif 'first_nick_name' in i:
                    vc_person["first_name"] = i['first_nick_name']

                # Handle missing email
                if i["email_1"] is None:
                    vc_person["email"] = ''
                else:
                    vc_person["email"] = i["email_1"]

                vc_person["address_1"] = h["address_1"]
                if h["address_2"] is None:
                    vc_person["address_2"] = ''
                else:
                    vc_person["address_2"] = h["address_2"]
                vc_person["city"] = h["city"]
                vc_person["zip"] = h["postal_code"]
                vc_person["state"] = h["state_province"]

                # Format LS Data for comparison
                try:
                    ls_customer["personpk"] = str(check_current["Customer"]["Contact"]["custom"])
                except:
                    ls_customer["personpk"] = ""

                ls_customer["last_name"] = check_current["Customer"]["lastName"]
                ls_customer["first_name"] = check_current["Customer"]["firstName"]

                # Handle missing email addresses.
                try:
                    ls_customer["email"] = check_current["Customer"]["Contact"]["Emails"]["ContactEmail"]["address"]
                except:
                    ls_customer["email"] = ''

                # Handle missing mailing addresses
                try:
                    ls_customer["address_1"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"][
                        "address1"]
                    ls_customer["address_2"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"][
                        "address2"]
                    ls_customer["city"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"]["city"]
                    ls_customer["zip"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"]["zip"]
                    ls_customer["state"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"]["state"]
                except:
                    ls_customer["address_1"] = ''
                    ls_customer["address_2"] = ''
                    ls_customer["city"] = ''
                    ls_customer["zip"] = ''
                    ls_customer["state"] = ''

                # Compare the data. Are the two dictionaries the same...
                if operation_json["sync_force"]:
                    force = True
                    applogs.info("Force sync enabled.")
                else:
                    force = False

                if not ls_customer == vc_person or force:
                    applogs.info("Updating customer {} {}.".format(vc_formatted['Customer']['firstName'],
                                                            vc_formatted['Customer']['lastName']))
                    vc_formatted['Customer']['customerID'] = check_current['Customer']['customerID']
                    # applogs.info(vc_formatted["Customer"])
                    ls.update("Customer/" + vc_formatted['Customer']['customerID'], vc_formatted["Customer"])
                else:
                    applogs.info("Record {} {} already up to date.".format(
                        vc_formatted['Customer']['firstName'],
                        vc_formatted['Customer']['lastName']))
            else:
                # Add new user when not found in LS
                applogs.info("Adding new Lightspeed Customer for {} {}".format(
                    vc_formatted['Customer']['firstName'],
                    vc_formatted['Customer']['lastName']))
                try:
                    new_customer = ls.create("Customer", vc_formatted["Customer"])
                    applogs.info("New Customer # {} Added: {} {}".format(
                        new_customer['Customer']['customerID'],
                        new_customer['Customer']['firstName'],
                        new_customer['Customer']['lastName']))
                except:
                    applogs.info("Unable to add new Lightspeed Customer for {} {}".format(
                        vc_formatted['Customer']['firstName'],
                        vc_formatted['Customer']['lastName']))


def get_payment_types(lightspeed_connection):
    ls_payment_types = dict()

    try:
        pt = lightspeed_connection.get("PaymentType")
        for i in pt['PaymentType']:
            ls_payment_types[i["name"]] = i["paymentTypeID"]
        return ls_payment_types
    except:
        applogs.info("Cannot get payment types from API.")


def get_shops(lightspeed_connection):
    ls_shops = dict()
    try:
        shop = lightspeed_connection.get("Shop")
        if isinstance(shop['Shop'], list):
            for s in shop['Shop']:
                ls_shops[s["name"]] = s
        else:
            ls_shops[shop["Shop"]["name"]] = shop['Shop']
        return ls_shops

    except:
        applogs.info("Error getting shop names.")
        sys.exit(2)


def roundup_decimal(x):
    """
    Self-Explanatory
    :param x: rounded up decimal to two places.
    :return:
    """
    return x.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def get_employees(lightspeed_connection):
    employees = dict()
    try:
        emp = lightspeed_connection.get("Employee")
        if isinstance(emp['Employee'], list):
            for s in emp['Employee']:
                name = s["firstName"] + " " + s["lastName"]
                employees[name] = s["employeeID"]
        else:
            name = emp["Shop"]["firstName"] + " " + emp["Shop"]["lastName"]
            employees[name] = emp["Shop"]["employeeID"]

        return employees
    except:
        applogs.info("Error getting employees from LS.")
        sys.exit(2)


def clear_account_balances(lightspeed_connection, customerID, balance, paymentID, creditAccountID, emp_id):
    try:
        formatted_request = {
                            "employeeID": emp_id,
                            "registerID": 1,
                            "shopID": 1,
                            "customerID": customerID,
                            "completed": 'true',
                            "SaleLines": {
                                "SaleLine": {
                                    "itemID": 0,
                                    "note": "Balance Cleared by LSVCConnector",
                                    "unitQuantity": 1,
                                    "unitPrice": -float(balance),
                                    "taxClassID": 0,
                                    "avgCost": 0,
                                    "fifoCost": 0
                                }
                            },
                            "SalePayments": {
                                "SalePayment": {
                                    "amount": -float(balance),
                                    "paymentTypeID": paymentID,
                                    "creditAccountID": creditAccountID
                                }
                            }
                        }
    except:
        applogs.info("Unable to format data to clear balances. Data missing?")

    try:
        lightspeed_connection.create('Sale', data=formatted_request)
        applogs.info("Cleared balance of {} of customerID {}".format(str(balance), str(customerID)))
    except:
        applogs.info("Unable to clear balance for customerID {}. Request follows.".format(str(customerID)))
        applogs.info(formatted_request)


def export_charge_balance(config, operation_json):
    """
    Export Charges from LS in CSV
    :return:
    """
    c = config
    ls = lightspeed_api.Lightspeed(c)

    current_store = operation_json["export_shop"]
    ls_shops = get_shops(ls)

    # Set current Timezone
    shop_timezone_name = ls_shops[current_store]["timeZone"]
    timezone = pytz.timezone(shop_timezone_name)
    shop_timezone_utc_offset = datetime.datetime.now(timezone).strftime('%z')
    shop_timezone_utc_offset_iso = shop_timezone_utc_offset[:3] + ":" + shop_timezone_utc_offset[3:]
    applogs.info(
        "Found %s timezone for shop named %s." % (shop_timezone_name, ls_shops[current_store]["name"]))

    # Customer Type
    ct = operation_json["type"]
    try:
        ls_customer_types = get_ls_customer_types(ls)
        ls_customerTypeID = ls_customer_types[ct]
    except:
        applogs.info("Unable to assign customer type from Lightspeed")
        sys.exit(2)

    applogs.info("Filtering results to customerType %s, id %s" % (ct, ls_customerTypeID))

    # Get selected shop
    shop = operation_json["export_shop"]
    shop_id = ls_shops[shop]['shopID']
    applogs.info("Filtering results to shop %s, id %s" % (shop, shop_id))

    # Are we clearing charges?
    try:
        if operation_json["export_clear_charges"]:
            pt = operation_json["export_clear_payment_type"]
            ls_payment_types = get_payment_types(ls)
            pt_id = ls_payment_types[pt]
    except:
        applogs.info("Not clearing charges. Missing export_clear_charges or export_clear_payment_type from json.")

    # Ensure there is an export location
    try:
        if os.path.isdir(operation_json["export_path"]):
            applogs.info("Exporting to %s" % (operation_json["export_path"]))
    except:
        applogs.info("Missing export_path in json.")

    # !! Sale Line Export !!

    # Export SaleLine Data
    try:
        begin_date = operation_json["export_date_begin"]
        # begin_date = begin_date.toPyDate()
    except:
        applogs.info("Missing export_date_begin in json.")

    # get begin and end dates
    try:
        end_date = operation_json["export_date_end"]
        # end_date = end_date.toPyDate()
    except:
        applogs.info("Missing export_date_end in json.")

    # Check date format.
    if len(str(begin_date)) != 10 or len(str(end_date)) != 10:
        applogs.info("Invalid begin or end date. Must be in format YYYY-MM-DD.")
        sys.exit(2)

    try:
        parameters = {}
        parameters['load_relations'] = 'all'
        parameters['completed'] = 'true'
        parameters['timeStamp'] = '{},{}T00:00:00-04:00,{}T23:59:59{}'.format("><",
                                                                              begin_date,
                                                                              end_date,
                                                                              shop_timezone_utc_offset_iso)
        applogs.info("Querying Lightspeed \"Sales\" data point with parameters " + str(parameters))
        salelines = ls.get("Sale", parameters=parameters)
    except:
        salelines = None
        applogs.info("Unable to get SaleLine data.")
        sys.exit(2)

    saleline_export_data = []

    # throw down some headers.
    f = ['person_id',
         'customer_account_number',
         'customer_name',
         'transaction_source',
         'transaction_type',
         'school_year',
         'item_date',
         'catalog_item_fk',
         'description',
         'quantity',
         'unit_price',
         'purchase_amount',
         'tax_amount',
         'total_amount',
         'pos_transaction_id'
         ]

    saleline_export_data.append(f)

    for i in salelines['Sale']:

        # Does this invoice have a payment that is on account.
        on_account = False

        if 'SalePayments' in i:
            if isinstance(i['SalePayments']['SalePayment'], list):
                for p in i['SalePayments']['SalePayment']:
                    if p['PaymentType']['code'] == 'SCA':
                        on_account = True
            else:
                if i['SalePayments']['SalePayment']['PaymentType']['code'] == 'SCA':
                    on_account = True

        if 'SaleLines' in i and on_account is True:

            # Check this is a customer we requested.
            if i['Customer']['customerTypeID'] != ls_customerTypeID:
                continue

            # Verify there are not mixed payments with on credit account
            if isinstance(i['SalePayments']['SalePayment'], list):
                for p in i['SalePayments']['SalePayment']:
                    if p['PaymentType']['code'] == 'SCA':
                        # Skip sales that mix payments with on_account
                        applogs.info("Skipping Sale #%s (%s %s): Other payments mixed with On Account." %
                                              (str(i['saleID']),
                                               str(i['Customer']['firstName']),
                                               str(i['Customer']['lastName'])))
                        continue

            # Depending on how many items sold,
            # types of salelines are returned.
            # List of dictionaries and a single dictionary.
            # Is this multiline sale?
            if isinstance(i['SaleLines']['SaleLine'], list):

                for s in i['SaleLines']['SaleLine']:

                    # Ignore this entry if it was not in the shop selected.
                    try:
                        if s['shopID'] != shop_id:
                            # applogs.info("ShopID for entry is not the shop that was requested, "
                            #                      "skipping entry: %s" % str(s))
                            continue
                    except:
                        applogs.info("Unable to determine shopID for entry: %s." % s)
                        continue

                    # Determine correct item description to use:
                    try:
                        if 'Item' in s:
                            if 'description' in s['Item']:
                                description = str(s['Item']['description'])
                            else:
                                description = "Unknown"
                        elif 'Note' in s:
                            if 'note' in s['Note']:
                                description = str(s['Note']['note'])
                                applogs.info("Debug Output: Sale line without actual item: " +
                                                      str(description))
                        else:
                            description = "Unknown"
                    except:
                        description = "Unknown"

                    # Format the entry to be added to our export file.
                    try:

                        saleline_single = [str(i['Customer']['companyRegistrationNumber']),
                                           str(i['Customer']['companyRegistrationNumber']),
                                           str(i['Customer']['firstName'] + " " + i['Customer']['lastName']),
                                           operation_json["export_options_transaction_source"],
                                           operation_json["export_options_transaction_type"],
                                           operation_json["export_options_school_year"],
                                           str(i['timeStamp'][:10]),
                                           operation_json["export_options_catalog_item"],
                                           str(description),
                                           str(s['unitQuantity']),
                                           Decimal(s['unitPrice']) -
                                           (Decimal(s['calcLineDiscount']) / int(s['unitQuantity'])),
                                           Decimal(s['displayableSubtotal']),
                                           roundup_decimal(Decimal(s['calcTax1'])),
                                           roundup_decimal(Decimal(s['calcTotal'])),
                                           str(i['saleID'])
                                           ]

                        saleline_export_data.append(saleline_single)
                    except:
                        applogs.info("Unable to append item (multisale) %s for Sale %s data to CSV." %
                                              (str(s['saleLineID']), str(i['saleID'])))
                        applogs.info("Debug Output: " + str(s))
            else:
                try:
                    # Is this a singleline sale?
                    if 'Item' in i["SaleLines"]["SaleLine"]:
                        # Need to be able to identify the item by it's type and not if it has items.
                        # What if only single misc charge?  To do this the way we clear balances needs to be change.
                        # Ideally we would want a Payment to CC Account.
                        # if isinstance(i["SaleLines"]["SaleLine"], dict):
                        # Ignore this entry if it was not in the shop selected.
                        if i["SaleLines"]["SaleLine"]["shopID"] != shop_id:
                            #applogs.info("ShopID for entry is not the shop that was requested, "
                            #                      "skipping entry: %s" % str(i["SaleLines"]["SaleLine"]))
                            continue

                        # Determine a description
                        try:
                            if 'Item' in i["SaleLines"]["SaleLine"]:
                                if 'description' in i["SaleLines"]["SaleLine"]['Item']:
                                    description = str(i["SaleLines"]["SaleLine"]['Item']['description'])
                                else:
                                    description = "Unknown"
                            elif 'Note' in i["SaleLines"]["SaleLine"]:
                                if 'note' in i["SaleLines"]["SaleLine"]['Note']:
                                    description = str(i["SaleLines"]["SaleLine"]['Note']['note'])
                                    applogs.info("Debug Output: Sale line without actual item: " +
                                                          str(description))
                            else:
                                description = "Unknown"
                        except:
                            description = "Unknown"

                        # Format the entry to be added to our export file.
                        saleline_single = [str(i['Customer']['companyRegistrationNumber']),
                                           str(i['Customer']['companyRegistrationNumber']),
                                           str(i['Customer']['firstName'] + " " + i['Customer']['lastName']),
                                           operation_json["export_options_transaction_source"],
                                           operation_json["export_options_transaction_type"],
                                           operation_json["export_options_school_year"],
                                           str(i["SaleLines"]["SaleLine"]['timeStamp'][:10]),
                                           operation_json["export_options_catalog_item"],
                                           str(description),
                                           str(i["SaleLines"]["SaleLine"]['unitQuantity']),
                                           Decimal(i["SaleLines"]["SaleLine"]['unitPrice']) -
                                           (Decimal(i["SaleLines"]["SaleLine"]['calcLineDiscount']) /
                                            int(i["SaleLines"]["SaleLine"]['unitQuantity'])),
                                           Decimal(i["SaleLines"]["SaleLine"]['displayableSubtotal']),
                                           roundup_decimal(
                                               Decimal(i["SaleLines"]["SaleLine"]['calcTax1'])),
                                           roundup_decimal(
                                               Decimal(i["SaleLines"]["SaleLine"]['calcTotal'])),
                                           str(i['saleID'])
                                           ]

                        saleline_export_data.append(saleline_single)
                except:
                    applogs.info("Unable to append (single) saleline for sale # " + str(i['saleID']),
                                          "info")
                    applogs.info("Debug Output: " + str(i["SaleLines"]["SaleLine"]))

    try:
        filename = operation_json["export_path"]
        filename = (filename + '/lightspeed_salelines_export_' +
                    datetime.datetime.now().strftime('%m%d%Y-%H%m%S') + '.csv')
        applogs.info(str(filename))
    except:
        applogs.info("Unable to determine export file.")
        sys.exit(2)

    try:
        with open(filename, 'w') as f:
            write = csv.writer(f)
            write.writerows(saleline_export_data)
    except:
        applogs.info("Unable to export salelines file.")
        sys.exit(2)

    # !! Account Balance Export !!
    try:
        # Get Customers with Balance on account. Used to export balances and clear accounts.
        customers = ls.get("Customer", parameters=dict(load_relations='["CreditAccount"]'))
    except:
        applogs.info("Unable to get Customer CreditAccount from Lightspeed.")
        sys.exit(2)

    try:
        export_data = []

        f = ['first_name',
             'last_name',
             'veracross_id',
             'lightspeed_cust_type',
             'balance',
             'lightspeed_cust_num']

        export_data.append(f)

        # If we are clearing - who is it marked as?
        try:
            emp = get_employees(ls)
            emp_id = emp[operation_json["export_clear_charges_employee_name"]]

        except:
            applogs.info("Couldn't determine charge clearing employee name. Using ID 1.")
            emp_id = 1

        for i in customers['Customer']:
            if 'CreditAccount' in i:
                if (float(i['CreditAccount']['balance']) > 0) and (int(i['customerTypeID']) == int(ls_customerTypeID)):
                    a = [i['firstName'],
                         i['lastName'],
                         i['companyRegistrationNumber'],
                         i['customerTypeID'],
                         i['CreditAccount']['balance'],
                         i['customerID']]
                    export_data.append(a)

                    if operation_json["export_clear_charges"]:

                        # Clear the balance for this account
                        clear_account_balances(int(i['customerID']),
                                               float(i['CreditAccount']['balance']),
                                               int(pt_id),
                                               int(i["creditAccountID"]),
                                               int(emp_id))

    except:
        applogs.info("Failed to format CreditBalance Export data.")
        sys.exit(2)

    try:
        filename = operation_json["export_path"]
        filename = filename + '/lightspeed_balance_export_' + \
                   datetime.datetime.now().strftime('%m%d%Y-%H%m%S') + '.xlsx'

        with open(filename, 'w') as f:
            write = csv.writer(f)
            write.writerows(export_data)

    except:
        applogs.info("Failed to export csv balance data.")
        sys.exit(2)


def main(argv):
    operation = ""
    operation_json = {
        "type": "",
        "sync_force": False,
        "sync_delete_missing": False,
        "sync_filters": {
            "after_date": "",
            "grade_level": ""
        }
    }

    try:
        opts, args = getopt.getopt(argv, "vhoc:j:t:fda:g:l:", [
            "version",
            "help",
            "operation=",
            "config=",
            "operation_json=",
            "type=",
            "sync_force",
            "sync_delete",
            "filter_after_date=",
            "filter_grade_level=",
            "log_path="])
    except getopt.GetoptError:
        print_help()
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print_help()
            sys.exit()
        elif opt in ("-v", "--version"):
            print(__version__)
            sys.exit()
        elif opt in ("-o", "--operation"):
            if arg == "sync":
                operation = "sync"
            elif arg == "export":
                operation = "export"
            else:
                print("Unknown operation. Use sync or export.")
                sys.exit()
        elif opt in ("-c", "--config"):
            config = load_json(arg)
        elif opt in ("-j", "--operation_json"):
            operation_json = load_json(arg)
        elif opt in ("-t", "--type"):
            operation_json["type"] = arg
        elif opt in ("-f", "--sync_force"):
            operation_json["sync_force"] = True
        elif opt in ("-d", "--sync_delete"):
            operation_json["sync_delete_missing"] = True
        elif opt in ("-a", "--filter_after_date"):
            operation_json["sync_filters"]["after_date"] = arg
        elif opt in ("-g", "--filter_grade_level"):
            operation_json["sync_filters"]["grade_level"] = arg
        elif opt in ("-l", "--log_path"):
            operation_json["log_path"] = arg
            try:
                # File Log
                logfile = logging.FileHandler(operation_json["log_path"])
                fileformat = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")
                logfile.setLevel(logging.INFO)
                logfile.setFormatter(fileformat)
                applogs.addHandler(logfile)
            except:
                print("Exception occurred while creating log file.")
                sys.exit(2)

    # Sync if there is a config
    if config:
        if operation == "sync":
            sync_ls_vc(config, operation_json)
            if operation_json["sync_delete_missing"]:
                delete_customer(config)
        if operation == "export":
            export_charge_balance(config, operation_json)
    else:
        applogs.info("Parameter config missing.")
        sys.exit(2)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        print_help()
        sys.exit(2)
    else:
        main(sys.argv[1:])

