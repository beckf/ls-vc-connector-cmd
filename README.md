# Veracross and LightspeedHQ POS Sync Connector CommandLine

This is a python script developed to provide integration between Veracross and Lightspeed. 
Many of the features offered here will be mirrored from the 
[LSVCConnector](https://github.com/beckf/lightspeed-vc-connector/wiki "LSVCConnector") PyQT app.

This script can be run as python in its own virtualenv or by using the pyinstaller binary found in 
[releases](https://github.com/beckf/ls-vc-connector-cmd/releases).

### <a name="getting-started"></a>How to Get Started
1) Follow the steps to creating an authorized Lightspeed app using the [LSVCConnector](https://github.com/beckf/lightspeed-vc-connector/wiki "LSVCConnector") PyQT app.
2) Export all of your settings from LSVCConnector using version >= 1.52.  
On the Settings Tab, click Export Settings.

**Keep this file safe as it contains your API credentials.**

3) Download the latest release from releases and uncompress. OR clone and create a new virtualenv using requirements.txt

Check out the help by running the binary with --help
```angular2html
/path/to/lsvcconnector-cmd --help
```

### Syncing Lightspeed with Veracross
Students, Faculty and Staff can be synced from Veracross to LightspeedHQ. 

First create a json file that defines how you want to sync the data. See sample_export_settings.json

JSON Options:
```angular2html
type: "Students" or "FacultyStaff" - This is the endpoint in Veracross which should match as CustomerType in LS
sync_force: false or true - Force updating all records in search.
sync_delete_missing: false or true - Delete any record of this type not found in Veracross. 
after_date: YYYY-MM-DD - Only sync records that have been updated after YYYY-MM-DD in Veracross.
grade_level: Grade Level ID from Veracross System Homepage in JSON list form -- [1,2,3,4]
```

Sample JSON Files:

All Students
```
{
  "type": "Students",
  "sync_force": false,
  "sync_delete_missing": false,
  "sync_filters": {
    "after_date": "",
    "grade_level": ""
  }
}
```

Students Grade 1-4 updated after 2022-12-02
```
{
  "type": "Students",
  "sync_force": false,
  "sync_delete_missing": false,
  "sync_filters": {
    "after_date": "2022-12-02",
    "grade_level": [1,2,3,4]
  }
}
```

Faculty records updated after 12-02-2022
```
{
  "type": "Faculty Staff",
  "sync_force": false,
  "sync_delete_missing": false,
  "sync_filters": {
    "after_date": "2022-12-02",
    "grade_level": ""
  }
}
```

Then execute using:
```angular2html
/path/to/lsvcconnector-cmd --operation=sync --config=config.json --operation_json=my_input_file.json
```

You can also mix cdm switches with json.  The switches will override the json file.

```angular2html
/path/to/lsvcconnector-cmd --operation=sync --config=config.json --operation_json=my_input_file.json --sync_type="Students" --filter_after_date="2022-12-01"
```

### Exporting from Lightspeed for Upload to Veracross CSV
Create a json definition file that contains the settings you want for your export. Files are generated in format the works with 
https://import.veracross.com/SCHOOLCODE

```angular2html
type: "Students" or "FacultyStaff" - This is the endpoint in Veracross which should match as CustomerType in LS
export_shop: The name of the shop as listed in Lightspeed.
export_path: Full OS path to folder for export file.
export_clear_charges: true or false - Clear charges of accounts that have balances. Only applies to those in this export.
export_clear_charges_employee_name: Name of the employee in Lightspeed that will show as who applied the credit.
export_clear_payment_type: The name of the tender type in Lightspeed that the cleared balance will be assigned to.
export_date_begin: Export charges begin search date.
export_date_end: Export charges end search date.
export_options_transaction_source: Veracross Transaction Source code applied to each item in export.
export_options_school_year: Veracross invoice school year. 
export_options_transaction_type: Veracross Transaction Source applied to each item in export.
export_options_catalog_item: Veracross catalog item
```

Example: 
```angular2html
{
  "type": "Student",
  "export_shop": "Bookstore",
  "export_path": "/home/user/store_exports",
  "export_clear_charges": false,
  "export_clear_charges_employee_name": "John Smith",
  "export_clear_payment_type" : "Charge Account",
  "export_date_begin": "2023-12-01",
  "export_date_end": "2023-12-31",
  "export_options_transaction_source": 2,
  "export_options_school_year": 2023,
  "export_options_transaction_type": 1,
  "export_options_catalog_item": 22
}
```

Execute the export operation.
```angular2html
/path/to/lsvcconnector-cmd --operation=export --config=config.json --operation_json=my_export_file.json
```