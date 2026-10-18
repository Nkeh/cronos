import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IncidentsBadge } from './IncidentsBadge'

describe('IncidentsBadge', () => {
  it('renders nothing at zero open incidents', () => {
    render(<IncidentsBadge count={0} />)
    expect(screen.queryByText('0')).toBeNull()
  })

  it('renders the count once there is at least one open incident', () => {
    render(<IncidentsBadge count={3} />)
    expect(screen.getByText('3')).not.toBeNull()
  })
})
