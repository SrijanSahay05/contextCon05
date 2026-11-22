import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import App from './App'

afterEach(cleanup)

test('counter increments on click', () => {
  render(<App />)
  const button = screen.getByRole('button', { name: /count is 0/i })
  fireEvent.click(button)
  expect(button.textContent).toMatch(/count is 1/i)
})
