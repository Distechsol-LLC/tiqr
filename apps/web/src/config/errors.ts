const ERROR_SERVICE_WORKER = 'Service Worker Register failed.';

const ERROR_USERNAME_REQUIRED = 'Enter your username.';
const ERROR_USERNAME_LONG = 'Username is too long.';
const ERROR_PASSWORD_REQUIRED = 'Enter your password.';
const ERROR_PASSWORD_LONG = 'Password is too long.';

const ERROR_INVALID_CREDENTIALS = 'Invalid username or password.';
const ERROR_RATE_LIMITED = 'Too many failed sign-ins. Try again later.';
const ERROR_NETWORK = 'Cannot reach the server. Check your connection and try again.';
const ERROR_SERVER = 'Something went wrong on the server. Try again.';

export {
  ERROR_INVALID_CREDENTIALS,
  ERROR_NETWORK,
  ERROR_PASSWORD_LONG,
  ERROR_PASSWORD_REQUIRED,
  ERROR_RATE_LIMITED,
  ERROR_SERVER,
  ERROR_SERVICE_WORKER,
  ERROR_USERNAME_LONG,
  ERROR_USERNAME_REQUIRED,
};
