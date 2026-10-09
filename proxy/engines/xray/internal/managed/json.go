package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
)

// CheckJSON refuses duplicate keys before native struct decoding can merge
// repeated objects differently from the validation view. Both memory and depth
// budgets must be selected by the owning caller before parsing.
func CheckJSON(payload []byte, maximumBytes int64, maximumDepth int) error {
	if maximumBytes <= 0 || maximumDepth <= 0 || int64(len(payload)) > maximumBytes {
		return errors.New("managed_json_capacity")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	if err := checkValue(decoder, 0, maximumDepth); err != nil {
		return err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return errors.New("managed_json_invalid")
	}
	return nil
}
func checkValue(decoder *json.Decoder, depth, maximum int) error {
	token, err := decoder.Token()
	if err != nil {
		return errors.New("managed_json_invalid")
	}
	delimiter, container := token.(json.Delim)
	if !container {
		return nil
	}
	if depth >= maximum {
		return errors.New("managed_json_capacity")
	}
	switch delimiter {
	case '{':
		names := make(map[string]bool)
		for decoder.More() {
			key, err := decoder.Token()
			name, ok := key.(string)
			if err != nil || !ok || names[name] {
				return errors.New("managed_json_duplicate_or_invalid")
			}
			names[name] = true
			if err := checkValue(decoder, depth+1, maximum); err != nil {
				return err
			}
		}
		if end, err := decoder.Token(); err != nil || end != json.Delim('}') {
			return errors.New("managed_json_invalid")
		}
	case '[':
		for decoder.More() {
			if err := checkValue(decoder, depth+1, maximum); err != nil {
				return err
			}
		}
		if end, err := decoder.Token(); err != nil || end != json.Delim(']') {
			return errors.New("managed_json_invalid")
		}
	default:
		return errors.New("managed_json_invalid")
	}
	return nil
}
