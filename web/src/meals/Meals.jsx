import { useEffect, useMemo, useState } from 'react'
import { fetchRecipes, fetchSettings } from './plan.js'
import { Slip } from './Slip.jsx'
import { KitchenLog } from './KitchenLog.jsx'

export function Meals() {
  const [settings, setSettings] = useState(null)
  const [recipes, setRecipes] = useState([])

  useEffect(() => {
    let gone = false
    fetchSettings()
      .then((body) => !gone && setSettings(body))
      .catch(() => !gone && setSettings({ dinnerHour: '17:30', weekStart: 'sat' }))
    fetchRecipes(120)
      .then((list) => !gone && setRecipes(list))
      .catch(() => !gone && setRecipes([]))
    return () => {
      gone = true
    }
  }, [])

  const recipesById = useMemo(() => {
    const map = new Map()
    for (const r of recipes) map.set(r.id, r)
    return map
  }, [recipes])

  const recipesByTitle = useMemo(() => {
    const map = new Map()
    for (const r of recipes) {
      const key = String(r.title || '')
        .trim()
        .toLowerCase()
      if (!key) continue
      const list = map.get(key) || []
      list.push(r)
      map.set(key, list)
    }
    return map
  }, [recipes])

  return (
    <div className="meals">
      <Slip settings={settings} recipesById={recipesById} recipesByTitle={recipesByTitle} />
      <KitchenLog />
    </div>
  )
}

export { fetchRecipes }
