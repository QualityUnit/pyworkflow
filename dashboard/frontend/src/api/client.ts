/**
 * API client for PyWorkflow Dashboard backend.
 */

// Use placeholder for runtime substitution in Docker, with fallback for development
const API_BASE_URL = '__VITE_API_URL_PLACEHOLDER__' !== '__VITE_API_URL_PLACEHOLDER__'
  ? '__VITE_API_URL_PLACEHOLDER__'
  : (import.meta.env.VITE_API_URL || 'http://localhost:8585')

export interface ApiError {
  detail: string
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error: ApiError = await response.json().catch(() => ({
      detail: `HTTP ${response.status}: ${response.statusText}`,
    }))
    throw new Error(error.detail)
  }
  return response.json()
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  })
  return handleResponse<T>(response)
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  return handleResponse<T>(response)
}

export const api = {
  get: apiGet,
  post: apiPost,
}
