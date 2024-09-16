import os
import requests

# Retrieve environment variables
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
authorize_url = os.getenv('GITHUB_AUTH_URL',
                          'https://github.com/login/oauth/authorize')
token_url = os.getenv('GITHUB_TOKEN_URL',
                      'https://github.com/login/oauth/access_token')
api_url = os.getenv('GITHUB_API_URL', 'https://api.github.com/user')

# Validate environment variables
if not client_id or not client_secret:
    print("Error: CLIENT_ID and CLIENT_SECRET must be set.")
    exit(1)

# Print values for validation
print(f"CLIENT_ID: {client_id[:10]}...")  # Show only the first 10 characters
print(f"CLIENT_SECRET: {client_secret[:10]}..."
      )  # Show only the first 10 characters
print(f"GITHUB_AUTH_URL: {authorize_url}")
print(f"GITHUB_TOKEN_URL: {token_url}")
print(f"GITHUB_API_URL: {api_url}")


def get_github_oauth_token(client_id, client_secret, code):
    """ Exchange authorization code for GitHub OAuth token """
    response = requests.post(token_url,
                             data={
                                 'client_id': client_id,
                                 'client_secret': client_secret,
                                 'code': code
                             },
                             headers={'Accept': 'application/json'})
    return response.json()


# Example usage for validation (assuming 'code' is provided)
# print(get_github_oauth_token(client_id, client_secret, 'example_authorization_code'))
