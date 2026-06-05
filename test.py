import requests

url = "https://api.loginextsolutions.com/LoginApp/login/authenticate"

payload = {
    "userName": "api.tms@aditya.co.id",
    "password": "9CE5Q8Jz_#xXR",
    "sessionExpiryTimeout": "60"
}

response = requests.post(url, json=payload)

print(response.status_code)
print(response.text)
