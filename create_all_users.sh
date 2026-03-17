#!/bin/bash
# Usage: bash create_all_users.sh YOUR_JWT_TOKEN
# Creates all 46 employees with empNo as password

TOKEN=$1
API="http://localhost:8000"

if [ -z "$TOKEN" ]; then
  echo "Usage: bash create_all_users.sh YOUR_JWT_TOKEN"
  exit 1
fi

create_user() {
  local name="$1" email="$2" role="$3" pod="$4" emp_no="$5" title="$6" reporting_to="$7"
  
  BODY=$(cat <<EOF
{
  "name": "$name",
  "email": "$email",
  "role": "$role",
  "pod": "$pod",
  "password": "$emp_no"
}
EOF
)
  
  RESPONSE=$(curl -s -X POST "$API/api/users/invite" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$BODY")
  
  echo "$name ($emp_no): $(echo $RESPONSE | python3 -c 'import sys,json; d=json.load(sys.stdin); print("✅ created" if "id" in d else "⚠ " + d.get("detail","error"))')"
}

echo "Creating 46 employees..."
echo "========================"

# Engineering managers (top level)
create_user "Abhishek Jain"                    "abhishek.jain@3scsolution.com"     "engineering_manager" "DPAI,EDM,SNOP,SNOE,PA,IAM,PLAT,SNPRM" "3SC1327"  "Vice President"
create_user "Sarfraz ."                        "sarfraz.khan@3scsolution.com"       "engineering_manager" "TMSNG"                                 "3SC1332"  "Senior Engineering Manager"
create_user "Vishal Raina"                     "vishal.raina@3scsolution.com"       "engineering_manager" "DPAI,EDM,SNOP,SNOE,PA,IAM,PLAT,SNPRM" "3SC1490"  "Project Manager"

# Tech leads
create_user "Srinivasan Seva"                  "seva.srinivasan@3scsolution.com"    "tech_lead"           "DPAI,EDM,SNOP,SNOE,PA,IAM,PLAT,SNPRM" "3SC1348"  "Engineering Manager"
create_user "Anoop Kumar Rai"                  "anoop.rai@3scsolution.com"          "tech_lead"           "DPAI,SNOP,SNOE,PA,PLAT"               "3SC839"   "Engineering Manager"
create_user "Kartik Keswani"                   "kartik.keswani@3scsolution.com"     "tech_lead"           "SNPRM"                                 "3SC1421"  "SDE3"

# Team: Srinivasan Seva
create_user "Swapnil Akash"                    "swapnil.akash@3scsolution.com"      "team_member"         "EDM"                                   "3SC1316"  "SDE2"
create_user "Aditya Narendra Warhade"          "aditya.narendra@3scsolution.com"    "team_member"         "EDM"                                   "3SC1199"  "SDE1"
create_user "Davudala Vishnuvardhan Goud"      "davudala.goud@3scsolution.com"      "team_member"         "EDM"                                   "3SC1447"  "SDE3"
create_user "Anand Verma"                      "anand.verma@3scsolution.com"        "team_member"         "DPAI,EDM,SNOP,SNOE,PA,PLAT,SNPRM"     "3SC1463"  "SDE3"
create_user "Prakash Kumar"                    "prakash.kumar@3scsolution.com"      "team_member"         "DPAI,EDM,SNOP,SNOE,PA,PLAT"           "3SC1516"  "SDE2"
create_user "Piyush Soni"                      "piyush.soni@3scsolution.com"        "team_member"         "EDM"                                   "3SC1543"  "SDE1"
create_user "Aditya Charan P N"                "aditya.charan@3scsolution.com"      "team_member"         "EDM"                                   "3SC1691"  "SDE1"
create_user "Gollasathyanarayanagari Sreekanth" "sreekanth@3scsolution.com"         "team_member"         "EDM"                                   "3SC1694"  "SDE1"
create_user "Tejaswani Upadhyay"               "tejaswani.upadhyay@3scsolution.com" "team_member"        "EDM"                                   "3SC1761"  "SDET1"
create_user "Mohit Kapoor"                     "mohit.kapoor@3scsolution.com"       "team_member"         "DPAI,EDM,SNOP,SNOE,PA,PLAT"           "3SC1795"  "SDE1"
create_user "Shubham Sinha"                    "shubham.sinha@3scsolution.com"      "team_member"         "EDM"                                   "3SC1799"  "SDET1"
create_user "Achal Kokatanoor"                 "achal.kokatanoor@3scsolution.com"   "team_member"         "DPAI,EDM,SNOP,SNOE,PA,PLAT"           "3SC1796"  "SDE1"
create_user "Vyom Gangwar"                     "vyom.gangwar@3scsolution.com"       "team_member"         "EDM"                                   "3SC1804"  "SDE1"

# Team: Anoop Kumar Rai
create_user "Aman Kumar Singh"                 "aman.singh@3scsolution.com"         "team_member"         "DPAI,EDM,SNOP,SNOE,PA,PLAT"           "3SC1206"  "SDE2"
create_user "Akanksha"                         "akanksha@3scsolution.com"           "team_member"         "DPAI,SNOP,SNOE,PA,PLAT"               "3SC1495"  "SDET2"
create_user "Akash Kumar"                      "akash.kumar1@3scsolution.com"       "team_member"         "DPAI,SNOP,SNOE,PA,PLAT"               "3SC1547"  "SDE2"
create_user "Ishu Rani"                        "ishu.rana@3scsolution.com"          "team_member"         "DPAI,SNOP,SNOE,PA,PLAT"               "3SC1565"  "SDET1"
create_user "Ashish Kumar Gopalika"            "ashish.gopalika@3scsolution.com"    "team_member"         "DPAI,SNOP,SNOE,PA,PLAT"               "3SC1627"  "SDE1"
create_user "Aastha Rai"                       "aastha.rai@3scsolution.com"         "team_member"         "DPAI,EDM,SNOP,SNOE,PA,PLAT"           "3SC1805"  "SDE1"
create_user "Nihar Sai Bansal"                 "nihar.bansal@3scsolution.com"       "team_member"         "DPAI,SNOP,SNOE,PA,PLAT"               "3SCI121"  "Intern"
create_user "Ashutosh Wahi"                    "ashutosh.wahi@3scsolution.com"      "team_member"         "DPAI,SNOP,SNOE,PA,PLAT"               "3SC1811"  "SDE1"

# Team: Kartik Keswani
create_user "Madem Guru Lakshmi Devi"          "guru.lakshmi@3scsolution.com"       "team_member"         "SNPRM"                                 "3SC1434"  "SDE2"
create_user "Niral Jain"                       "niral.jain@3scsolution.com"         "team_member"         "SNPRM"                                 "3SC1432"  "SDE3"
create_user "Sudipta Sundar Sahoo"             "sudipta.sahoo@3scsolution.com"      "team_member"         "SNPRM"                                 "3SC1488"  "SDE2"
create_user "Ramprasath Murali"                "ramprasath@3scsolution.com"         "team_member"         "SNPRM"                                 "3SC1531"  "SDET1"
create_user "Ritesh Pradeep Panjwani"          "ritesh.panjwani@3scsolution.com"    "team_member"         "SNPRM"                                 "3SC1572"  "SDE3"
create_user "Prashant Poonia"                  "prashant.poonia@3scsolution.com"    "team_member"         "SNPRM"                                 "3SC1604"  "SDE2"
create_user "Harsh Malik"                      "harsh.malik@3scsolution.com"        "team_member"         "SNPRM"                                 "3SC1747"  "SDE1"
create_user "Shivam Srivastava"                "shivam.srivastava@3scsolution.com"  "team_member"         "SNPRM"                                 "3SC1815"  "SDET1"

# Team: Sarfraz
create_user "Pavanesh Kumar"                   "pavanesh.kumar@3scsolution.com"     "team_member"         "TMSNG"                                 "3SC1392"  "SDE1"
create_user "Rahul Kumar Pandey"               "rahul.pandey@3scsolution.com"       "team_member"         "TMSNG"                                 "3SC1389"  "SDE1"
create_user "Ajeet kumar Chaurasia"            "ajeet.chaurasia@3scsolution.com"    "team_member"         "TMSNG"                                 "3SC1207"  "SDE1"
create_user "Vaishali Kandpal"                 "vaishali.kandpal@3scsolution.com"   "team_member"         "TMSNG"                                 "3SC1213"  "SDE1"
create_user "Kumar Aditya"                     "kumar.aditya@3scsolution.com"       "team_member"         "TMSNG"                                 "3SC1218"  "Business Analyst"
create_user "Ankush Sisodia"                   "ankush.sisodia@3scsolution.com"     "team_member"         "TMSNG"                                 "3SC1445"  "SDE2"
create_user "Akhilakh Alvi"                    "akhilakh.alvi@3scsolution.com"      "team_member"         "TMSNG"                                 "3SC1443"  "SDET1"
create_user "Abhishek Kumar"                   "abhishek1.kumar@3scsolution.com"    "team_member"         "TMSNG"                                 "3SC1540"  "SDE1"
create_user "Aaditya Varshney"                 "aaditya.varshney@3scsolution.com"   "team_member"         "TMSNG"                                 "3SC1687"  "SDE2"
create_user "Praveen Kumar"                    "praveen.kumar1@3scsolution.com"     "team_member"         "TMSNG"                                 "3SC1788"  "SDE2"
create_user "Rajnandani Pandey"                "rajnandani.pandey@3scsolution.com"  "team_member"         "TMSNG"                                 "3SCIU014" "Intern"

echo ""
echo "========================"
echo "Done! Now run employee sync:"
echo "node sync_employees.js"