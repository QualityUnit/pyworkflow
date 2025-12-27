/**
 * React hook for D3 integration.
 * Safely manages D3 lifecycle within React components.
 */

import { useRef, useEffect } from 'react'
import * as d3 from 'd3'

/**
 * Hook to create and manage a D3 visualization within a React component.
 *
 * @param renderFn - Function that receives the D3 selection and renders the visualization
 * @param deps - Dependencies array that triggers re-render when changed
 * @returns Ref to attach to the SVG element
 */
export function useD3<T extends SVGSVGElement>(
  renderFn: (svg: d3.Selection<T, unknown, null, undefined>) => void,
  deps: React.DependencyList
) {
  const ref = useRef<T>(null)

  useEffect(() => {
    if (ref.current) {
      const svg = d3.select(ref.current)
      renderFn(svg)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return ref
}
