import requests

url = "https://api.loginextsolutions.com/LoginApp/login/authenticate"

payload = {
    "userName":xxxx,
    "password":xxxx,
    "sessionExpiryTimeout": "60"
}

response = requests.post(url, json=payload)

print(response.status_code)
print(response.text)
