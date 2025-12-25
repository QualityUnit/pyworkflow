/**
 * Code editor component using CodeMirror for JSON editing.
 */

import { useCallback } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { json } from '@codemirror/lang-json'
import { cn } from '@/lib/utils'

interface CodeEditorProps {
  value: string
  onChange?: (value: string) => void
  placeholder?: string
  readOnly?: boolean
  className?: string
  minHeight?: string
}

export function CodeEditor({
  value,
  onChange,
  placeholder = '{}',
  readOnly = false,
  className,
  minHeight = '100px',
}: CodeEditorProps) {
  const handleChange = useCallback(
    (val: string) => {
      onChange?.(val)
    },
    [onChange]
  )

  return (
    <div
      className={cn(
        'rounded-md border border-input bg-background text-sm',
        'focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2',
        className
      )}
    >
      <CodeMirror
        value={value}
        onChange={handleChange}
        extensions={[json()]}
        placeholder={placeholder}
        readOnly={readOnly}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLineGutter: true,
          highlightActiveLine: true,
          bracketMatching: true,
          closeBrackets: true,
          autocompletion: true,
          indentOnInput: true,
        }}
        style={{
          minHeight,
          fontSize: '14px',
        }}
        theme="light"
        className="[&_.cm-editor]:!outline-none [&_.cm-scroller]:!font-mono"
      />
    </div>
  )
}
