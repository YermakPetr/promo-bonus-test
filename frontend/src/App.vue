<script setup>
import { ref } from 'vue'
import api from './services/api'

const status = ref('unknown')

api
  .get('/user')
  .then(() => {
    status.value = 'authenticated'
  })
  .catch((error) => {
    status.value = error.response?.status === 401 ? 'unauthenticated' : 'error'
  })
</script>

<template>
  <main>
    <h1>Promo Bonus Test</h1>
    <p>Vue 3 + Vite frontend, talking to the Laravel API.</p>
    <p>Auth status: <strong>{{ status }}</strong></p>
  </main>
</template>
