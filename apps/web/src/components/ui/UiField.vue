<script setup lang="ts">
defineProps<{ label: string; hint?: string; error?: string | null; required?: boolean }>()
</script>

<template>
  <label class="st-field">
    <span class="st-field__label"
      ><span
        >{{ label
        }}<span v-if="required" class="st-field__required" aria-hidden="true">*</span></span
      ><span class="st-field__side"><slot name="label-action" /></span
    ></span>
    <slot />
    <small v-if="hint && !error" class="st-field__hint">{{ hint }}</small>
    <small v-if="error" class="st-field__error" role="alert">{{ error }}</small>
  </label>
</template>

<style scoped>
.st-field,
.ui-field {
  display: grid;
  gap: 6px;
  font-family: var(--st-font);
}
.st-field__label,
.ui-field__label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--st-text-main);
}
.st-field__hint,
.ui-field__hint {
  color: var(--st-text-muted);
  font-size: 0.75rem;
}
.st-field__error,
.ui-field__error {
  color: var(--st-error);
  font-size: 0.75rem;
  font-weight: 600;
}
.st-field__label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.st-field__required {
  color: var(--st-danger);
  margin-left: 2px;
}
.st-field__side:empty {
  display: none;
}
.st-field__ok {
  color: var(--st-success);
  font-size: 0.75rem;
  font-weight: 600;
}
.st-field__bad {
  color: var(--st-danger);
  font-size: 0.75rem;
  font-weight: 600;
}
.st-field__hintbox {
  margin: 2px 0 0;
  padding: 8px 12px;
  border-radius: var(--st-radius-sm);
  background: var(--st-info-tint);
  color: var(--st-text-main);
  font-size: 0.8rem;
  font-weight: 400;
}
.st-radio-card span {
  display: grid;
}
.st-radio-card small {
  color: var(--st-text-muted);
  font-size: 0.75rem;
  font-weight: 400;
}
</style>
