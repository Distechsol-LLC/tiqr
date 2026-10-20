const ERROR_SERVICE_WORKER = 'Service Worker Register failed.';

const ERROR_USERNAME_REQUIRED = 'Enter your username.';
const ERROR_USERNAME_LONG = 'Username is too long.';
const ERROR_PASSWORD_REQUIRED = 'Enter your password.';
const ERROR_PASSWORD_LONG = 'Password is too long.';

const ERROR_INVALID_CREDENTIALS = 'Invalid username or password.';
const ERROR_RATE_LIMITED = 'Too many failed sign-ins. Try again later.';
const ERROR_NETWORK = 'Cannot reach the server. Check your connection and try again.';
const ERROR_SERVER = 'Something went wrong on the server. Try again.';
const ERROR_SESSION_ENDED = 'Your session has ended. Sign in again.';

const ERROR_VISITOR_NAME_REQUIRED = 'Enter the visitor name.';
const ERROR_VISITOR_NAME_LONG = 'Visitor name is too long.';
const ERROR_VISITOR_TYPE_REQUIRED = 'Enter the visitor type.';
const ERROR_VISITOR_TYPE_LONG = 'Visitor type is too long.';
const ERROR_VALID_FROM_REQUIRED = 'Pick when the ticket starts.';
const ERROR_VALID_UNTIL_REQUIRED = 'Pick when the ticket ends.';
const ERROR_VALID_UNTIL_BEFORE = 'The end must not be before the start.';
const ERROR_ASSIGNEE_REQUIRED = 'Pick an account.';
const ERROR_PASSWORD_MISMATCH = 'Passwords do not match.';

export {
  ERROR_ASSIGNEE_REQUIRED,
  ERROR_INVALID_CREDENTIALS,
  ERROR_NETWORK,
  ERROR_PASSWORD_LONG,
  ERROR_PASSWORD_MISMATCH,
  ERROR_PASSWORD_REQUIRED,
  ERROR_RATE_LIMITED,
  ERROR_SERVER,
  ERROR_SERVICE_WORKER,
  ERROR_SESSION_ENDED,
  ERROR_USERNAME_LONG,
  ERROR_USERNAME_REQUIRED,
  ERROR_VALID_FROM_REQUIRED,
  ERROR_VALID_UNTIL_BEFORE,
  ERROR_VALID_UNTIL_REQUIRED,
  ERROR_VISITOR_NAME_LONG,
  ERROR_VISITOR_NAME_REQUIRED,
  ERROR_VISITOR_TYPE_LONG,
  ERROR_VISITOR_TYPE_REQUIRED,
};
