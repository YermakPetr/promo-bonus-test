<?php

namespace App\Http\Requests;

use Illuminate\Contracts\Validation\ValidationRule;
use Illuminate\Foundation\Http\FormRequest;

class ClaimPromoCodeRequest extends FormRequest
{
    /**
     * Determine if the user is authorized to make this request.
     */
    public function authorize(): bool
    {
        // The auth:sanctum middleware already guards this route.
        return true;
    }

    /**
     * Get the validation rules that apply to the request.
     *
     * @return array<string, ValidationRule|array<mixed>|string>
     */
    public function rules(): array
    {
        return [
            'code' => ['required', 'string', 'min:6', 'max:12', 'regex:/^[A-Za-z0-9]+$/'],
        ];
    }

    /**
     * Get custom messages for validator errors.
     *
     * @return array<string, string>
     */
    public function messages(): array
    {
        return [
            'code.required' => 'Promo code is required.',
            'code.min' => 'Promo code must be between 6 and 12 characters long.',
            'code.max' => 'Promo code must be between 6 and 12 characters long.',
            'code.regex' => 'Promo code may only contain Latin letters and digits.',
        ];
    }
}
