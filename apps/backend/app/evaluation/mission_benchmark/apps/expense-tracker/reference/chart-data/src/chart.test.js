const test = require('node:test')
const assert = require('node:assert/strict')
const { barChartData } = require('./chart')

test('empty totals give no bars', () => {
  assert.deepEqual(barChartData({}), [])
})
