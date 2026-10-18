const COPY = {
  meals: 'Meals',
  recipes: 'Recipes',
  notes: 'Notes',
  chats: 'Chats',
  missing: 'This page is not on the table',
}

export function Placeholder({ id }) {
  return (
    <section className="placeholder" data-tab={id}>
      <h1>{COPY[id] || COPY.missing}</h1>
    </section>
  )
}
