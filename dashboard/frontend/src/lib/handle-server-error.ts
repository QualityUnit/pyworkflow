import { AxiosError } from 'axios'
import { toast } from 'sonner'

export function handleServerError(error: Error) {
  // eslint-disable-next-line no-console
  console.error(error)

  let message = 'An unexpected error occurred'

  if (error instanceof AxiosError) {
    if (error.response?.data?.message) {
      message = error.response.data.message
    } else if (error.message) {
      message = error.message
    }
  } else if (error.message) {
    message = error.message
  }

  toast.error(message)
}
