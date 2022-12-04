import veracross_api
import lightspeed_api
import sys
import getopt
import os
import datetime
import pandas
from decimal import Decimal, ROUND_HALF_UP
import logging
import json

__version__ = "0.1"

# Creating logger
applogs = logging.getLogger(__name__)
applogs.setLevel(logging.DEBUG)

# File Log
logfile = logging.FileHandler("sync.log")
fileformat = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")
logfile.setLevel(logging.INFO)
logfile.setFormatter(fileformat)

# Stream Log
stream = logging.StreamHandler()
streamformat = logging.Formatter("%(levelname)s:%(module)s:%(message)s")
stream.setLevel(logging.DEBUG)
stream.setFormatter(streamformat)

# Adding all handlers to the logging
applogs.addHandler(logfile)
applogs.addHandler(stream)


def print_help():
    print(
        """
        main.py:
        --version = Script version
        --help = This text
        --sync = Perform a sync operation          
        --config = Complete path to config file from LSVCConnector (see sample_config.json)
        --sync_json = Optional JSON file with sync parameters.
            Mix of JSON and other switches allowed.
            Other switches override JSON.
        --sync_type = VC role to sync ("Students" or "Faculty Staff")
        --sync_force = Force update all VC records in LS.
        --sync_delete = Search all LS records and delete all not found in VC.
        --filter_after_date = Only update records updated in VC after date formatted as YYYY-MM-DD
        --filter_grade_level = Comma seperated list of grades by VC ID to sync ("1,2,3,4,20")

        /usr/local/bin/python3 main.py --sync --config=config.json --sync_json=/path/to/sync_json.json
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


def sync_ls_vc(config, sync_json):

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
    if "after_date" in sync_json["sync_filters"]:
        if sync_json["sync_filters"]["after_date"]:
            param.update({"updated_after": str(sync_json["sync_filters"]["after_date"])})

    # If we are working with students, add additional parameters.
    if "sync_type" in sync_json:
        if sync_json["sync_type"] == "Students":
            applogs.info("Getting Veracross Students (Current)")

            # Add a grade level filter
            if "grade_level" in sync_json["sync_filters"]:
                if isinstance(sync_json["sync_filters"]["grade_level"], list):
                    grade_list_string = ",".join(str(item) for item in sync_json["sync_filters"]["grade_level"])
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
        if sync_json["sync_type"] == "Faculty Staff":

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
        applogs.info("sync_type of 'Faculty Staff' or 'Students' not found in sync options json file.")
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
                if sync_json["sync_force"]:
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


def main(argv):
    operation = ""
    sync_json = {
        "sync_type": "",
        "sync_force": False,
        "sync_delete_missing": False,
        "sync_filters": {
            "after_date": "",
            "grade_level": ""
        }
    }

    try:
        opts, args = getopt.getopt(argv, "vhsc:j:t:fda:g:", [
            "version",
            "help",
            "sync",
            "config=",
            "sync_json=",
            "sync_type=",
            "sync_force",
            "sync_delete",
            "filter_after_date=",
            "filter_grade_level="])
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
        elif opt in ("-s", "--sync"):
            operation = "sync"
        elif opt in ("-c", "--config"):
            config = load_json(arg)
        elif opt in ("-j", "--sync_json"):
            sync_json = load_json(arg)
        elif opt in ("-t", "--sync_type"):
            sync_json["sync_type"] = arg
        elif opt in ("-f", "--sync_force"):
            sync_json["sync_force"] = True
        elif opt in ("-d", "--sync_delete"):
            sync_json["sync_delete_missing"] = True
        elif opt in ("-a", "--filter_after_date"):
            sync_json["sync_filters"]["after_date"] = arg
        elif opt in ("-g", "--filter_grade_level"):
            sync_json["sync_filters"]["grade_level"] = arg

    # Sync if there is a config
    if config and operation == "sync":
        sync_ls_vc(config, sync_json)
    else:
        applogs.info("Parameter config missing.")
        sys.exit(2)

    # Delete if requested
    if config and sync_json["sync_delete_missing"]:
        delete_customer(config)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        print_help()
        sys.exit(2)
    else:
        main(sys.argv[1:])

