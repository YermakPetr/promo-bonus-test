<script setup>
import { ref } from 'vue'
import api from './services/api'
import PromoClaimForm from './components/PromoClaimForm.vue'
import PromoClaimHistory from './components/PromoClaimHistory.vue'

const status = ref('unknown')
const balance = ref(null)
const historyRef = ref(null)

api
  .get('/user')
  .then(() => {
    status.value = 'authenticated'
  })
  .catch((error) => {
    status.value = error.response?.status === 401 ? 'unauthenticated' : 'error'
  })

function handleClaimed({ claim, balance: newBalance }) {
  balance.value = newBalance
  historyRef.value?.prependClaim(claim)
}
</script>

<template>
  <main>
    <h1>Promo Bonus Test</h1>
    <p>Vue 3 + Vite frontend, talking to the Laravel API.</p>
    <p>Auth status: <strong>{{ status }}</strong></p>
    <p>Balance: <strong>{{ balance !== null ? balance : '—' }}</strong></p>

    <PromoClaimForm @claimed="handleClaimed" />

    <PromoClaimHistory ref="historyRef" />
  </main>
</template>
