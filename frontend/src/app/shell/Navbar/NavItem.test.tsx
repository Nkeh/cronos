import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { Home, Activity } from 'lucide-react'
import { NavItem } from './NavItem'

describe('NavItem', () => {
  it('sets aria-current="page" only on the item matching the current path', () => {
    render(
      <MemoryRouter initialEntries={['/monitors']}>
        <NavItem to="/" label="Overview" icon={Home} />
        <NavItem to="/monitors" label="Monitors" icon={Activity} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: 'Overview' }).getAttribute('aria-current')).toBeNull()
    expect(screen.getByRole('link', { name: 'Monitors' }).getAttribute('aria-current')).toBe('page')
  })

  it('"/" only matches exactly (end routing), not every path', () => {
    render(
      <MemoryRouter initialEntries={['/monitors']}>
        <NavItem to="/" label="Overview" icon={Home} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Overview' }).getAttribute('aria-current')).toBeNull()
  })
})
