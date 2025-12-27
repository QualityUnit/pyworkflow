export function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined
  const value = `; ${document.cookie}`
  const parts = value.split(`; ${name}=`)
  if (parts.length === 2) {
    return parts.pop()?.split(';').shift()
  }
  return undefined
}

export function setCookie(
  name: string,
  value: string,
  maxAge: number = 60 * 60 * 24 * 365
): void {
  document.cookie = `${name}=${value}; max-age=${maxAge}; path=/`
}

export function removeCookie(name: string): void {
  document.cookie = `${name}=; max-age=0; path=/`
}
