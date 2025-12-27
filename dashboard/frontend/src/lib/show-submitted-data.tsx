import { toast } from 'sonner'

export function showSubmittedData(data: unknown) {
  toast.success('Form submitted', {
    description: (
      <pre className="mt-2 w-[340px] rounded-md bg-slate-950 p-4">
        <code className="text-white">{JSON.stringify(data, null, 2)}</code>
      </pre>
    ),
  })
}
