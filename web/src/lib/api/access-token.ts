let accessToken: string | undefined;

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(token: string | undefined) {
  accessToken = token;
}

export function clearAccessToken() {
  accessToken = undefined;
}
