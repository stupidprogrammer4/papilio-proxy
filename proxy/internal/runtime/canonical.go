package runtime

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"sort"
	"unicode/utf8"
)

func canonicalJSON(payload []byte) ([]byte, error) {
	if !utf8.Valid(payload) {
		return nil, errors.New("canonical_json_invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	var value any
	if decoder.Decode(&value) != nil {
		return nil, errors.New("canonical_json_invalid")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return nil, errors.New("canonical_json_invalid")
	}
	var buffer bytes.Buffer
	if err := writeCanonical(&buffer, value); err != nil {
		return nil, err
	}
	return buffer.Bytes(), nil
}
func canonicalString(value string) []byte {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(value)
	encoded := bytes.TrimSuffix(buffer.Bytes(), []byte("\n"))
	var result bytes.Buffer
	for i := 0; i < len(encoded); i++ {
		if encoded[i] == '\\' && i+1 < len(encoded) {
			if encoded[i+1] == '\\' {
				result.Write(encoded[i : i+2])
				i++
				continue
			}
			if i+6 <= len(encoded) && (string(encoded[i:i+6]) == `\u2028` || string(encoded[i:i+6]) == `\u2029`) {
				if encoded[i+5] == '8' {
					result.WriteString("\u2028")
				} else {
					result.WriteString("\u2029")
				}
				i += 5
				continue
			}
		}
		result.WriteByte(encoded[i])
	}
	return result.Bytes()
}
func writeCanonical(buffer *bytes.Buffer, value any) error {
	switch item := value.(type) {
	case nil:
		buffer.WriteString("null")
	case bool:
		if item {
			buffer.WriteString("true")
		} else {
			buffer.WriteString("false")
		}
	case json.Number:
		buffer.WriteString(item.String())
	case string:
		buffer.Write(canonicalString(item))
	case []any:
		buffer.WriteByte('[')
		for i, element := range item {
			if i > 0 {
				buffer.WriteByte(',')
			}
			if err := writeCanonical(buffer, element); err != nil {
				return err
			}
		}
		buffer.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(item))
		for key := range item {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		buffer.WriteByte('{')
		for i, key := range keys {
			if i > 0 {
				buffer.WriteByte(',')
			}
			buffer.Write(canonicalString(key))
			buffer.WriteByte(':')
			if err := writeCanonical(buffer, item[key]); err != nil {
				return err
			}
		}
		buffer.WriteByte('}')
	default:
		return errors.New("canonical_json_invalid")
	}
	return nil
}
func membershipDigest(memberships []Membership) (string, error) {
	content, err := json.Marshal(memberships)
	if err != nil {
		return "", errors.New("membership_json_invalid")
	}
	canonical, err := canonicalJSON(content)
	if err != nil {
		return "", err
	}
	return checksum(canonical), nil
}
