/** Clear a partially established session without exposing the session token. */
export function clearStoredLoginToken(
  storage: Pick<Storage, 'removeItem'> = window.localStorage,
): void {
  storage.removeItem('token')
}
