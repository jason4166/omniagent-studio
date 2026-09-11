import type { Json } from './types'

function text(value: Json | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, 240) : null
}

export function citationPresentation(metadata: Record<string, Json>) {
  const filename = text(metadata.source_name)?.split(/[\\/]/).at(-1) || null
  const section = text(metadata.section)
  const page = metadata.page_number
  return {
    title: section || filename?.replace(/\.(md|markdown|txt|pdf)$/i, '') || '引用资料',
    filename,
    page: typeof page === 'number' && Number.isSafeInteger(page) && page > 0 ? page : null,
  }
}
