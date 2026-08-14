<script setup>
import { ref } from 'vue'
import api from '../services/api'

const emit = defineEmits(['claimed'])

const code = ref('')
const status = ref('idle') // idle | loading | success | error
const message = ref('')

function resetFeedback() {
  if (status.value === 'success' || status.value === 'error') {
    status.value = 'idle'
    message.value = ''
  }
}

async function submitClaim() {
  if (status.value === 'loading' || !code.value.trim()) return

  status.value = 'loading'
  message.value = ''

  try {
    const { data } = await api.post('/promo/claim', { code: code.value.trim() })

    status.value = 'success'
    message.value = `Promo code applied: +${data.claim.amount}`
    emit('claimed', { claim: data.claim, balance: data.balance })
    code.value = ''
  } catch (error) {
    status.value = 'error'
    message.value = error.response?.data?.message || 'Something went wrong. Please try again.'
  }
}
</script>

<template>
  <form class="promo-form" @submit.prevent="submitClaim">
    <label class="promo-form__label" for="promo-code">Promo code</label>
    <div class="promo-form__row">
      <input
        id="promo-code"
        v-model="code"
        class="promo-form__input"
        type="text"
        placeholder="e.g. WELCOME10"
        autocomplete="off"
        :disabled="status === 'loading'"
        @input="resetFeedback"
      />
      <button class="promo-form__submit" type="submit" :disabled="status === 'loading' || !code.trim()">
        {{ status === 'loading' ? 'Applying…' : 'Apply' }}
      </button>
    </div>

    <p v-if="status === 'error'" class="promo-form__message promo-form__message--error">{{ message }}</p>
    <p v-else-if="status === 'success'" class="promo-form__message promo-form__message--success">{{ message }}</p>
  </form>
</template>

<style scoped>
.promo-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.promo-form__label {
  font-size: 0.875rem;
  color: var(--text);
}

.promo-form__row {
  display: flex;
  gap: 0.5rem;
}

.promo-form__input {
  flex: 1;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  background: var(--bg);
  color: var(--text-h);
  font: inherit;
}

.promo-form__input:disabled {
  opacity: 0.6;
}

.promo-form__submit {
  padding: 0.5rem 1.25rem;
  border: 1px solid var(--accent-border);
  border-radius: 0.375rem;
  background: var(--accent-bg);
  color: var(--accent);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.promo-form__submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.promo-form__message {
  margin: 0;
  font-size: 0.875rem;
}

.promo-form__message--error {
  color: #dc2626;
}

.promo-form__message--success {
  color: #16a34a;
}
</style>
