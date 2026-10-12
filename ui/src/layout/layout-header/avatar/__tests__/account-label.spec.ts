import assert from 'node:assert/strict'
import test from 'node:test'
import { avatarAccountLabel } from '../account-label.ts'

test('portal accounts show the friendly nick and hide the technical username', () => {
  const hash = `portal_${'ab'.repeat(24)}`
  const label = avatarAccountLabel({
    source: 'PORTAL',
    nick_name: 'admin（门户）',
    username: hash,
  })
  assert.equal(label.portal, true)
  assert.equal(label.primary, 'admin（门户）')
  assert.equal(label.title, 'admin（门户）')
  assert.equal(label.showUsername, false)
  assert.equal(label.username, '')
  assert.equal(label.title.includes(hash), false)
  assert.equal(label.primary.includes('portal_'), false)
})

test('local accounts keep the nickname and username', () => {
  const label = avatarAccountLabel({
    source: 'LOCAL',
    nick_name: '系统管理员',
    username: 'admin',
  })
  assert.equal(label.portal, false)
  assert.equal(label.primary, '系统管理员')
  assert.equal(label.title, '系统管理员')
  assert.equal(label.showUsername, true)
  assert.equal(label.username, 'admin')
})

test('a long portal nick stays the title and is not joined with the username', () => {
  const nick = '名'.repeat(140) + '（门户）'
  const label = avatarAccountLabel({
    source: 'PORTAL',
    nick_name: nick,
    username: `portal_${'cd'.repeat(24)}`,
  })
  assert.equal(label.title, nick)
  assert.equal(label.primary, nick)
  assert.equal(label.showUsername, false)
})
