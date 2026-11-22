import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test } from 'vitest'
import App from './App'

beforeEach(() => {
  window.location.hash = ''
})
afterEach(cleanup)

test('renders the thesis composer on For you', () => {
  render(<App />)
  expect(screen.getByLabelText(/your investment thesis/i)).toBeTruthy()
})

test('sidebar lists the four folders with counts', () => {
  render(<App />)
  const nav = screen.getByRole('navigation', { name: /folders/i })
  const labels = within(nav)
    .getAllByRole('link')
    .map((l) => l.textContent)
  expect(labels).toEqual(['For you4', 'Watching2', 'In outreach1', 'Discarded0'])
})

test('lists For you startups sorted by score', () => {
  render(<App />)
  const list = screen.getByRole('region', { name: 'For you' })
  const names = within(list)
    .getAllByRole('heading', { level: 3 })
    .map((h) => h.textContent)
  expect(names).toEqual(['Ledgerline', 'Freightwise', 'Clinicaloop', 'Kiln Robotics'])
})

test('opening a startup shows its details in a dialog', () => {
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Ledgerline' }))
  const dialog = screen.getByRole('dialog', { name: 'Ledgerline' })
  for (const name of ['Hiring', 'News', 'Grants & funding']) {
    expect(within(dialog).getByRole('heading', { name })).toBeTruthy()
  }
  expect(within(dialog).getByRole('button', { name: /open page/i })).toBeTruthy()
})
