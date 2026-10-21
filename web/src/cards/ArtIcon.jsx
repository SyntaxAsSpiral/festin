// One of the artist's engraved icons (public/art/icons), drawn in the text's current colour.
export function ArtIcon({ name }) {
  return <span className="art-ic" style={{ '--art': `url(/art/icons/${name}.svg)` }} aria-hidden="true" />
}
