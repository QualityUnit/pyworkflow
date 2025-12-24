/**
 * Workflows list page.
 */

import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useWorkflows } from '@/hooks/use-workflows'

export function WorkflowsList() {
  const { data, isLoading, error, refetch } = useWorkflows()

  return (
    <>
      <Header>
        <h1 className="text-lg font-semibold">Registered Workflows</h1>
        <div className="ms-auto flex items-center space-x-4">
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main>
        <div className="mb-4 flex items-center justify-between">
          <div className="text-muted-foreground">
            {data && `${data.count} workflow${data.count !== 1 ? 's' : ''} registered`}
          </div>
          <Button variant="outline" onClick={() => refetch()}>
            Refresh
          </Button>
        </div>

        {isLoading && (
          <div className="text-center py-8 text-muted-foreground">
            Loading workflows...
          </div>
        )}

        {error && (
          <div className="text-center py-8 text-destructive">
            Error loading workflows: {error.message}
          </div>
        )}

        {data && data.items.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            No workflows registered. Define workflows using the @workflow decorator.
          </div>
        )}

        {data && data.items.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {data.items.map((workflow) => (
              <Card key={workflow.name}>
                <CardHeader>
                  <CardTitle className="text-lg">{workflow.name}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {workflow.max_duration && (
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-foreground">Max Duration:</span>
                        <Badge variant="outline">{workflow.max_duration}</Badge>
                      </div>
                    )}
                    {Object.keys(workflow.metadata).length > 0 && (
                      <div>
                        <span className="text-sm text-muted-foreground">Metadata:</span>
                        <pre className="mt-1 text-xs bg-muted p-2 rounded overflow-x-auto">
                          {JSON.stringify(workflow.metadata, null, 2)}
                        </pre>
                      </div>
                    )}
                    {!workflow.max_duration && Object.keys(workflow.metadata).length === 0 && (
                      <span className="text-sm text-muted-foreground">
                        No additional configuration
                      </span>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </Main>
    </>
  )
}
