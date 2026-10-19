import { describe, expect, it } from 'vitest'
import { collectAttachments } from './Composer.jsx'

function browserFile({ name, type, content }) {
  return new File([content], name, { type })
}

describe('composer attachments', () => {
  it('keeps photos as data URLs and documents as {name, text}', async () => {
    const png = browserFile({
      name: 'dish.png',
      type: 'image/png',
      content: new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]),
    })
    const doc = browserFile({
      name: 'cake-density.md',
      type: 'text/markdown',
      content: '# Cake\n\ndensity notes',
    })
    const next = await collectAttachments({ photos: [], files: [] }, [png, doc])
    expect(next.note).toBe('')
    expect(next.photos).toHaveLength(1)
    expect(next.photos[0].name).toBe('dish.png')
    expect(String(next.photos[0].data)).toMatch(/^data:image\/png;base64,/)
    expect(next.files).toEqual([{ name: 'cake-density.md', text: '# Cake\n\ndensity notes' }])
  })

  it('rejects a fourth-plus photo and unknown types', async () => {
    const photos = Array.from({ length: 4 }, (_, i) => ({
      name: `p${i}.png`,
      data: 'data:image/png;base64,xx',
    }))
    const extra = browserFile({
      name: 'more.png',
      type: 'image/png',
      content: new Uint8Array([137, 80, 78, 71]),
    })
    const over = await collectAttachments({ photos, files: [] }, [extra])
    expect(over.note).toMatch(/four photos/)
    expect(over.photos).toHaveLength(4)

    const pdf = browserFile({ name: 'scan.pdf', type: 'application/pdf', content: '%PDF' })
    const bad = await collectAttachments({ photos: [], files: [] }, [pdf])
    expect(bad.note).toMatch(/image|\.md|\.txt/)
    expect(bad.files).toHaveLength(0)
  })

  it('accepts .txt by extension when the browser leaves type empty', async () => {
    const doc = browserFile({ name: 'notes.txt', type: '', content: 'plain notes' })
    const next = await collectAttachments({ photos: [], files: [] }, [doc])
    expect(next.files).toEqual([{ name: 'notes.txt', text: 'plain notes' }])
  })
})
