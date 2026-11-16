import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'

function samplePdf() {
  const content = 'BT /F1 14 Tf 72 720 Td (The budget of Project Atlas is 75 000 euros.) Tj ET'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = objects.map((object, index) => {
    const start = pdf.length
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
    return String(start).padStart(10, '0') + ' 00000 n '
  })
  const crossReference = pdf.length
  return Buffer.from(
    pdf + `xref\n0 6\n0000000000 65535 f \n${offsets.join('\n')}\ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${crossReference}\n%%EOF\n`,
  )
}

test('upload, ask, open a highlighted citation, and restore the conversation', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Créer un compte', exact: true }).click()
  await page.getByLabel('Adresse e-mail').fill(`e2e-${randomUUID()}@example.com`)
  await page.getByLabel('Mot de passe').fill('local browser fixture password')
  await page.getByRole('button', { name: 'Créer mon compte' }).click()

  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: 'Importer un PDF' }).click()
  await (await chooser).setFiles({ name: 'Atlas test.pdf', mimeType: 'application/pdf', buffer: samplePdf() })
  const card = page.locator('.library-file').filter({ hasText: 'Atlas test.pdf' })
  await expect(card.getByText('Prêt', { exact: true })).toBeVisible({ timeout: 15000 })

  await page.getByRole('button', { name: 'Nouvelle conversation' }).click()
  const form = page.getByRole('dialog', { name: 'Nouvelle conversation' })
  await form.getByLabel('Titre', { exact: true }).fill('Atlas E2E')
  await form.getByRole('checkbox', { name: 'Atlas test.pdf' }).check()
  await form.getByRole('button', { name: 'Créer la conversation' }).click()
  await page.getByLabel('Ta question').fill('What is the budget of Project Atlas?')
  await page.getByRole('button', { name: 'Envoyer' }).click()
  await expect(page.getByText('75 000 euros', { exact: true })).toBeVisible()
  await expect(page.locator('.pdf-citation-badge')).toContainText('p.1')
  await expect(page.locator('.cited-text').first()).toBeVisible()

  await page.getByRole('button', { name: 'Masquer le PDF' }).click()
  await expect(page.locator('.document-column')).toBeHidden()
  await page.getByRole('button', { name: 'Afficher le PDF' }).click()
  await expect(page.locator('.pdf-citation-badge')).toBeVisible()
  const divider = page.getByRole('separator', { name: 'Largeur du panneau PDF' })
  const oldWidth = (await page.locator('.document-column').boundingBox())!.width
  await divider.press('ArrowRight')
  await expect.poll(async () => (await page.locator('.document-column').boundingBox())!.width).toBeGreaterThan(oldWidth)

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Atlas E2E' })).toBeVisible()
  await expect(page.getByText('75 000 euros', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Se déconnecter' }).click()
  await expect(page.getByRole('heading', { name: 'Se connecter' })).toBeVisible()
})
