/**
 * Modal component for creating a new workflow run.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod/v4'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { CodeEditor } from '@/components/ui/code-editor'
import { startRun } from '@/api/runs'
import type { Workflow, WorkflowParameter } from '@/api/types'

interface NewRunModalProps {
  workflow: Workflow | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

// Build a Zod schema dynamically based on workflow parameters
function buildFormSchema(parameters: WorkflowParameter[]) {
  const shape: Record<string, z.ZodType> = {}

  for (const param of parameters) {
    let fieldSchema: z.ZodType

    switch (param.type) {
      case 'string':
        fieldSchema = param.required ? z.string().min(1, 'Required') : z.string().optional()
        break
      case 'number':
        fieldSchema = param.required
          ? z.string().min(1, 'Required').transform((val) => Number(val))
          : z.string().optional().transform((val) => (val ? Number(val) : undefined))
        break
      case 'boolean':
        fieldSchema = z.boolean().optional()
        break
      case 'array':
      case 'object':
      case 'any':
      default:
        // For complex types, we'll use a JSON string that gets parsed
        fieldSchema = param.required
          ? z.string().min(1, 'Required')
          : z.string().optional()
        break
    }

    shape[param.name] = fieldSchema
  }

  return z.object(shape)
}

// Get default value for a parameter
function getDefaultValue(param: WorkflowParameter): string | boolean {
  if (param.default !== null && param.default !== undefined) {
    if (param.type === 'boolean') {
      return Boolean(param.default)
    }
    if (param.type === 'array' || param.type === 'object') {
      return JSON.stringify(param.default, null, 2)
    }
    return String(param.default)
  }

  // Return empty defaults based on type
  switch (param.type) {
    case 'boolean':
      return false
    case 'array':
      return '[]'
    case 'object':
      return '{}'
    default:
      return ''
  }
}

export function NewRunModal({ workflow, open, onOpenChange }: NewRunModalProps) {
  const navigate = useNavigate()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const parameters = workflow?.parameters ?? []

  // Build schema and defaults based on parameters
  const formSchema = useMemo(() => buildFormSchema(parameters), [parameters])

  const defaultValues = useMemo(() => {
    const values: Record<string, string | boolean> = {}
    for (const param of parameters) {
      values[param.name] = getDefaultValue(param)
    }
    return values
  }, [parameters])

  const form = useForm({
    resolver: zodResolver(formSchema),
    defaultValues,
  })

  // Reset form when workflow changes
  useEffect(() => {
    if (workflow) {
      form.reset(defaultValues)
    }
  }, [workflow, defaultValues, form])

  const handleSubmit = useCallback(
    async (values: Record<string, unknown>) => {
      if (!workflow) return

      setIsSubmitting(true)

      try {
        // Parse JSON strings for complex types
        const kwargs: Record<string, unknown> = {}
        for (const param of parameters) {
          const value = values[param.name]

          if (value === undefined || value === '') {
            if (param.required) {
              throw new Error(`${param.name} is required`)
            }
            continue
          }

          if (param.type === 'array' || param.type === 'object' || param.type === 'any') {
            try {
              kwargs[param.name] = JSON.parse(value as string)
            } catch {
              throw new Error(`Invalid JSON for ${param.name}`)
            }
          } else {
            kwargs[param.name] = value
          }
        }

        const result = await startRun({
          workflow_name: workflow.name,
          kwargs,
        })

        toast.success(`Workflow run started: ${result.run_id}`)
        onOpenChange(false)

        // Navigate to the run detail page
        navigate({ to: '/runs/$runId', params: { runId: result.run_id } })
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to start workflow run')
      } finally {
        setIsSubmitting(false)
      }
    },
    [workflow, parameters, onOpenChange, navigate]
  )

  if (!workflow) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New Workflow Run</DialogTitle>
          <DialogDescription>
            Start a new run of <span className="font-semibold">{workflow.name}</span>
            {workflow.description && (
              <span className="block text-xs mt-1">{workflow.description}</span>
            )}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            {parameters.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                This workflow has no parameters.
              </p>
            ) : (
              parameters.map((param) => (
                <FormField
                  key={param.name}
                  control={form.control}
                  name={param.name}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        {param.name}
                        {param.required && <span className="text-destructive ml-1">*</span>}
                      </FormLabel>

                      {param.type === 'boolean' ? (
                        <FormControl>
                          <div className="flex items-center space-x-2">
                            <Switch
                              checked={field.value as boolean}
                              onCheckedChange={field.onChange}
                            />
                            <span className="text-sm text-muted-foreground">
                              {field.value ? 'True' : 'False'}
                            </span>
                          </div>
                        </FormControl>
                      ) : param.type === 'array' ||
                        param.type === 'object' ||
                        param.type === 'any' ? (
                        <FormControl>
                          <CodeEditor
                            value={field.value as string}
                            onChange={field.onChange}
                            placeholder={param.type === 'array' ? '[]' : '{}'}
                            minHeight="120px"
                          />
                        </FormControl>
                      ) : param.type === 'number' ? (
                        <FormControl>
                          <Input
                            type="number"
                            {...field}
                            value={field.value as string}
                            placeholder={`Enter ${param.name}`}
                          />
                        </FormControl>
                      ) : (
                        <FormControl>
                          <Input
                            {...field}
                            value={field.value as string}
                            placeholder={`Enter ${param.name}`}
                          />
                        </FormControl>
                      )}

                      <FormDescription className="text-xs">
                        Type: {param.type}
                        {param.default !== null && param.default !== undefined && (
                          <span>
                            {' '}
                            | Default:{' '}
                            {typeof param.default === 'object'
                              ? JSON.stringify(param.default)
                              : String(param.default)}
                          </span>
                        )}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ))
            )}

            <DialogFooter className="pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Starting...
                  </>
                ) : (
                  'Run Workflow'
                )}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
