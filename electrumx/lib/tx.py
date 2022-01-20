# Copyright (c) 2016-2017, Neil Booth
# Copyright (c) 2017, the ElectrumX authors
#
# All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
# and warranty status of this software.

'''Transaction-related classes and functions.'''

from dataclasses import dataclass
from hashlib import blake2s
from typing import Sequence

from electrumx.lib.hash import sha256, double_sha256, hash_to_hex_str
from electrumx.lib.script import OpCodes, Script
from electrumx.lib.util import (
    unpack_le_int32_from, unpack_le_int64_from, unpack_le_uint16_from,
    unpack_be_uint16_from,
    unpack_le_uint32_from, unpack_le_uint64_from, pack_le_int32, pack_varint,
    pack_le_uint16, pack_le_uint32, pack_le_int64, pack_varbytes,
)

ZERO = bytes(32)
MINUS_1 = 4294967295


@dataclass
class Tx:
    '''Class representing a transaction.'''
    __slots__ = 'version', 'inputs', 'outputs', 'locktime'
    version: int
    inputs: Sequence['TxInput']
    outputs: Sequence['TxOutput']
    locktime: int

    def serialize(self):
        return b''.join((
            pack_le_int32(self.version),
            pack_varint(len(self.inputs)),
            b''.join(tx_in.serialize() for tx_in in self.inputs),
            pack_varint(len(self.outputs)),
            b''.join(tx_out.serialize() for tx_out in self.outputs),
            pack_le_uint32(self.locktime)
        ))


@dataclass
class TxInput:
    '''Class representing a transaction input.'''
    __slots__ = 'prev_hash', 'prev_idx', 'script', 'sequence'
    prev_hash: bytes
    prev_idx: int
    script: bytes
    sequence: int

    def __str__(self):
        script = self.script.hex()
        prev_hash = hash_to_hex_str(self.prev_hash)
        return (f"Input({prev_hash}, {self.prev_idx:d}, script={script}, "
                f"sequence={self.sequence:d})")

    def is_generation(self):
        '''Test if an input is generation/coinbase like'''
        return self.prev_idx == MINUS_1 and self.prev_hash == ZERO

    def serialize(self):
        return b''.join((
            self.prev_hash,
            pack_le_uint32(self.prev_idx),
            pack_varbytes(self.script),
            pack_le_uint32(self.sequence),
        ))


@dataclass
class TxOutput:
    __slots__ = 'value', 'pk_script'
    value: int
    pk_script: bytes

    def serialize(self):
        return b''.join((
            pack_le_int64(self.value),
            pack_varbytes(self.pk_script),
        ))


class Deserializer:
    '''Deserializes blocks into transactions.

    External entry points are read_tx(), read_tx_and_hash(),
    read_tx_and_vsize() and read_block().

    This code is performance sensitive as it is executed 100s of
    millions of times during sync.
    '''

    TX_HASH_FN = staticmethod(double_sha256)

    def __init__(self, binary, start=0):
        assert isinstance(binary, bytes)
        self.binary = binary
        self.binary_length = len(binary)
        self.cursor = start

    def read_tx(self):
        '''Return a deserialized transaction.'''
        return Tx(
            self._read_le_int32(),  # version
            self._read_inputs(),    # inputs
            self._read_outputs(),   # outputs
            self._read_le_uint32()  # locktime
        )

    def read_tx_and_hash(self):
        '''Return a (deserialized TX, tx_hash) pair.

        The hash needs to be reversed for human display; for efficiency
        we process it in the natural serialized order.
        '''
        start = self.cursor
        return self.read_tx(), self.TX_HASH_FN(self.binary[start:self.cursor])

    def read_tx_and_vsize(self):
        '''Return a (deserialized TX, vsize) pair.'''
        return self.read_tx(), self.binary_length

    def read_tx_block(self):
        '''Returns a list of (deserialized_tx, tx_hash) pairs.'''
        read = self.read_tx_and_hash
        # Some coins have excess data beyond the end of the transactions
        return [read() for _ in range(self._read_varint())]

    def _read_inputs(self):
        read_input = self._read_input
        return [read_input() for i in range(self._read_varint())]

    def _read_input(self):
        return TxInput(
            self._read_nbytes(32),   # prev_hash
            self._read_le_uint32(),  # prev_idx
            self._read_varbytes(),   # script
            self._read_le_uint32()   # sequence
        )

    def _read_outputs(self):
        read_output = self._read_output
        return [read_output() for i in range(self._read_varint())]

    def _read_output(self):
        return TxOutput(
            self._read_le_int64(),  # value
            self._read_varbytes(),  # pk_script
        )

    def _read_byte(self):
        cursor = self.cursor
        self.cursor += 1
        return self.binary[cursor]

    def _read_nbytes(self, n):
        cursor = self.cursor
        self.cursor = end = cursor + n
        assert self.binary_length >= end
        return self.binary[cursor:end]

    def _read_varbytes(self):
        return self._read_nbytes(self._read_varint())

    def _read_varint(self):
        n = self.binary[self.cursor]
        self.cursor += 1
        if n < 253:
            return n
        if n == 253:
            return self._read_le_uint16()
        if n == 254:
            return self._read_le_uint32()
        return self._read_le_uint64()

    def _read_le_int32(self):
        result, = unpack_le_int32_from(self.binary, self.cursor)
        self.cursor += 4
        return result

    def _read_le_int64(self):
        result, = unpack_le_int64_from(self.binary, self.cursor)
        self.cursor += 8
        return result

    def _read_le_uint16(self):
        result, = unpack_le_uint16_from(self.binary, self.cursor)
        self.cursor += 2
        return result

    def _read_be_uint16(self):
        result, = unpack_be_uint16_from(self.binary, self.cursor)
        self.cursor += 2
        return result

    def _read_le_uint32(self):
        result, = unpack_le_uint32_from(self.binary, self.cursor)
        self.cursor += 4
        return result

    def _read_le_uint64(self):
        result, = unpack_le_uint64_from(self.binary, self.cursor)
        self.cursor += 8
        return result


@dataclass
class TxSegWit:
    '''Class representing a SegWit transaction.'''
    __slots__ = ('version', 'marker', 'flag', 'inputs', 'outputs', 'witness',
                 'locktime')
    version: int
    marker: int
    flag: int
    inputs: Sequence
    outputs: Sequence
    witness: Sequence
    locktime: int


class DeserializerSegWit(Deserializer):

    # https://bitcoincore.org/en/segwit_wallet_dev/#transaction-serialization

    def _read_witness(self, fields):
        read_witness_field = self._read_witness_field
        return [read_witness_field() for i in range(fields)]

    def _read_witness_field(self):
        read_varbytes = self._read_varbytes
        return [read_varbytes() for i in range(self._read_varint())]

    def _read_tx_parts(self):
        '''Return a (deserialized TX, tx_hash, vsize) tuple.'''
        start = self.cursor
        marker = self.binary[self.cursor + 4]
        if marker:
            # We could call super().read_tx here but the call stack is
            # expensive when executed millions of times.
            tx = Tx(
                self._read_le_int32(),  # version
                self._read_inputs(),    # inputs
                self._read_outputs(),   # outputs
                self._read_le_uint32()  # locktime
            )
            tx_hash = self.TX_HASH_FN(self.binary[start:self.cursor])
            return tx, tx_hash, self.binary_length

        # Ugh, this is tasty.
        version = self._read_le_int32()
        orig_ser = self.binary[start:self.cursor]

        marker = self._read_byte()
        flag = self._read_byte()

        start = self.cursor
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        orig_ser += self.binary[start:self.cursor]

        base_size = self.cursor - start
        witness = self._read_witness(len(inputs))

        start = self.cursor
        locktime = self._read_le_uint32()
        orig_ser += self.binary[start:self.cursor]
        vsize = (3 * base_size + self.binary_length) // 4

        return TxSegWit(version, marker, flag, inputs, outputs, witness,
                        locktime), self.TX_HASH_FN(orig_ser), vsize

    def read_tx(self):
        return self._read_tx_parts()[0]

    def read_tx_and_hash(self):
        tx, tx_hash, _vsize = self._read_tx_parts()
        return tx, tx_hash

    def read_tx_and_vsize(self):
        tx, _tx_hash, vsize = self._read_tx_parts()
        return tx, vsize


class DeserializerAuxPow(Deserializer):
    VERSION_AUXPOW = (1 << 8)

    def read_auxpow(self):
        '''Reads and returns the CAuxPow data'''

        # We first calculate the size of the CAuxPow instance and then
        # read it as bytes in the final step.
        start = self.cursor

        self.read_tx()  # AuxPow transaction
        self.cursor += 32  # Parent block hash
        merkle_size = self._read_varint()
        self.cursor += 32 * merkle_size  # Merkle branch
        self.cursor += 4  # Index
        merkle_size = self._read_varint()
        self.cursor += 32 * merkle_size  # Chain merkle branch
        self.cursor += 4  # Chain index
        self.cursor += 80  # Parent block header

        end = self.cursor
        self.cursor = start
        return self._read_nbytes(end - start)

    def read_header(self, static_header_size):
        '''Return the AuxPow block header bytes'''

        # We are going to calculate the block size then read it as bytes
        start = self.cursor

        version = self._read_le_uint32()
        if version & self.VERSION_AUXPOW:
            self.cursor = start
            self.cursor += static_header_size  # Block normal header
            self.read_auxpow()
            header_end = self.cursor
        else:
            header_end = start + static_header_size

        self.cursor = start
        return self._read_nbytes(header_end - start)


class DeserializerAuxPowSegWit(DeserializerSegWit, DeserializerAuxPow):
    pass


class DeserializerEquihash(Deserializer):
    def read_header(self, static_header_size):
        '''Return the block header bytes'''
        start = self.cursor
        # We are going to calculate the block size then read it as bytes
        self.cursor += static_header_size
        solution_size = self._read_varint()
        self.cursor += solution_size
        header_end = self.cursor
        self.cursor = start
        return self._read_nbytes(header_end)


class DeserializerEquihashSegWit(DeserializerSegWit, DeserializerEquihash):
    pass


class DeserializerZcash(DeserializerEquihash):
    def read_tx(self):
        header = self._read_le_uint32()
        overwintered = ((header >> 31) == 1)
        if overwintered:
            version = header & 0x7fffffff
            self.cursor += 4  # versionGroupId
        else:
            version = header

        is_overwinter_v3 = version == 3
        is_sapling_v4 = version == 4

        base_tx = Tx(
            version,
            self._read_inputs(),    # inputs
            self._read_outputs(),   # outputs
            self._read_le_uint32()  # locktime
        )

        if is_overwinter_v3 or is_sapling_v4:
            self.cursor += 4  # expiryHeight

        has_shielded = False
        if is_sapling_v4:
            self.cursor += 8  # valueBalance
            shielded_spend_size = self._read_varint()
            self.cursor += shielded_spend_size * 384  # vShieldedSpend
            shielded_output_size = self._read_varint()
            self.cursor += shielded_output_size * 948  # vShieldedOutput
            has_shielded = shielded_spend_size > 0 or shielded_output_size > 0

        if base_tx.version >= 2:
            joinsplit_size = self._read_varint()
            if joinsplit_size > 0:
                joinsplit_desc_len = 1506 + (192 if is_sapling_v4 else 296)
                # JSDescription
                self.cursor += joinsplit_size * joinsplit_desc_len
                self.cursor += 32  # joinSplitPubKey
                self.cursor += 64  # joinSplitSig

        if is_sapling_v4 and has_shielded:
            self.cursor += 64  # bindingSig

        return base_tx


class DeserializerHorizen(DeserializerEquihash):
    OP_CHECKBLOCKATHEIGHT = OpCodes.OP_NOP5

    def _read_output(self):
        value = self._read_le_int64()
        script = self.remove_replay_protection(self._read_varbytes())

        return TxOutput(
            value,
            script
        )

    def remove_replay_protection(self, script):
        try:
            ops = Script.get_ops(script)
            if ops[-1] == self.OP_CHECKBLOCKATHEIGHT:
                blk = ops[-3]  # block hash
                if isinstance(blk, tuple) and blk[0] == 32:
                    rp_idx = script.index(blk[1]) - 1  # include the push op
                    return script[:rp_idx]  # strip replay protection data
        except Exception:
            pass
        return script

    def _read_cert(self):
        self._read_nbytes(32)   # sidechain id
        self._read_le_uint32()  # epoch number
        self._read_le_uint64()  # quality

        # end epoch cum sidechain transaction comm tree root
        end_epoch_cum_sc_tx_comm_tree_root_len = self._read_varint()
        self.cursor += end_epoch_cum_sc_tx_comm_tree_root_len

        # sidechain proof
        sc_proof_len = self._read_varint()
        self.cursor += sc_proof_len

        # vfield element certificate field
        v_field_element_certificate_field_len = self._read_varint()
        for x in range(v_field_element_certificate_field_len):
            field_len = self._read_varint()
            self.cursor += field_len

        # vbit vector certificate field
        v_bit_vector_certificate_field_len = self._read_varint()
        for x in range(v_bit_vector_certificate_field_len):
            field_len = self._read_varint()
            self.cursor += field_len

        self._read_le_uint64()  # forward transfer sidechain fee
        self._read_le_uint64()  # mainchain backwards transfer request sidechain fee

    def _read_csw_inputs(self):
        csw_len = self._read_varint()

        for x in range(csw_len):
            self._read_le_uint64()  # value
            self._read_nbytes(32)   # sidechain id
            nullifer_len = self._read_varint()  # nullifer
            self.cursor += nullifer_len

            self._read_nbytes(20)  # pub key hash

            sc_proof_len = self._read_varint()  # sidechain proof
            self.cursor += sc_proof_len

            act_cert_data_hash_len = self._read_varint()  # actCertDataHash
            self.cursor += act_cert_data_hash_len

            ceasing_cum_sc_tx_comm_tree_len = self._read_varint()  # ceasingCumScTxCommTree
            self.cursor += ceasing_cum_sc_tx_comm_tree_len

            redeem_script_len = self._read_varint()  # redeemScriptLength
            self.cursor += redeem_script_len

    def _read_sc_outputs(self):
        sc_output_len = self._read_varint()

        for x in range(sc_output_len):
            self._read_le_int32()   # withdrawalEpochLength
            self._read_le_uint64()  # value
            self._read_nbytes(32)   # address
            custom_data_len = self._read_varint()  # customData
            self._read_nbytes(custom_data_len)

            # constant data
            constant_data_option = self._read_varint()
            if constant_data_option == 1:
                constant_data_len = self._read_varint()
                self._read_nbytes(constant_data_len)

            # wCertVk
            w_cert_vk_len = self._read_varint()
            self._read_nbytes(w_cert_vk_len)

            # wCeasedVkOption
            w_ceased_vk_option = self._read_varint()
            if w_ceased_vk_option == 1:
                w_ceased_vk_len = self._read_varint()
                self._read_nbytes(w_ceased_vk_len)

            # vFieldElementCertificateFieldConfig
            v_field_element_certificate_field_config_len = self._read_varint()
            for y in range(v_field_element_certificate_field_config_len):
                self.cursor += 1  # self._read_le_uint8()

            # vBitVectorCertificateFieldConfig
            v_bit_vector_certificate_field_config_len = self._read_varint()
            for z in range(v_bit_vector_certificate_field_config_len):
                bit_vector = self._read_le_uint32()
                max_compressed_size = self._read_le_uint32()

            self._read_le_uint64()  # forward transfer fee
            self._read_le_uint64()  # mainchain backward transfer request fee
            self.cursor += 1  # self._read_le_uint8() #mbtrRequestDataLength

    def _read_ft_outputs(self):
        ft_len = self._read_varint()

        for x in range(ft_len):
            self._read_le_uint64()  # value
            self._read_nbytes(32)   # address
            self._read_nbytes(32)   # sidechain id
            self._read_nbytes(20)   # mc return address

    def _read_mbtr_outputs(self):
        mbtr_len = self._read_varint()

        for x in range(mbtr_len):
            self._read_nbytes(32)  # sidechain id
            sc_request_data_len = self._read_varint()

            for y in range(sc_request_data_len):
                len = self._read_varint()
                self.cursor += len

            self._read_nbytes(20)   # pubKeyHash
            self._read_le_uint64()  # sidechain fee

    def _read_sidechain(self):
        self._read_csw_inputs()
        self._read_sc_outputs()
        self._read_ft_outputs()
        self._read_mbtr_outputs()

    def read_tx(self):
        version = self._read_le_int32()  # can be negative for Groth txs

        if version == -5:
            self._read_cert()

        inputs = self._read_inputs()
        outputs = self._read_outputs()

        if version == -4:
            self._read_sidechain()

        locktime = self._read_le_uint32() if version != -5 else 0

        base_tx = Tx(
            version,
            inputs,
            outputs,
            locktime
        )

        if version >= 2 or version == -3:
            joinsplit_size = self._read_varint()
            if joinsplit_size > 0:
                is_groth = version == -3
                joinsplit_desc_len = 1506 + (192 if is_groth else 296)
                # JSDescription
                self.cursor += joinsplit_size * joinsplit_desc_len
                self.cursor += 32  # joinSplitPubKey
                self.cursor += 64  # joinSplitSig

        return base_tx


@dataclass
class TxPIVX:
    '''Class representing a PIVX transaction.'''
    __slots__ = 'version', "txtype", 'inputs', 'outputs', 'locktime'
    version: int
    txtype: int
    inputs: Sequence['TxInput']
    outputs: Sequence['TxOutput']
    locktime: int

    def serialize(self):
        return b''.join((
            pack_le_uint16(self.version),
            pack_le_uint16(self.txtype),
            pack_varint(len(self.inputs)),
            b''.join(tx_in.serialize() for tx_in in self.inputs),
            pack_varint(len(self.outputs)),
            b''.join(tx_out.serialize() for tx_out in self.outputs),
            pack_le_uint32(self.locktime)
        ))


class DeserializerPIVX(Deserializer):
    def read_tx(self):
        header = self._read_le_uint32()
        tx_type = header >> 16  # DIP2 tx type
        if tx_type:
            version = header & 0x0000ffff
        else:
            version = header

        if tx_type and version < 3:
            version = header
            tx_type = 0

        base_tx = TxPIVX(
            version,
            tx_type,
            self._read_inputs(),  # inputs
            self._read_outputs(),  # outputs
            self._read_le_uint32()  # locktime
        )

        if version >= 3:  # >= sapling
            self._read_varint()
            self.cursor += 8  # valueBalance
            shielded_spend_size = self._read_varint()
            self.cursor += shielded_spend_size * 384  # vShieldedSpend
            shielded_output_size = self._read_varint()
            self.cursor += shielded_output_size * 948  # vShieldedOutput
            self.cursor += 64  # bindingSig
            if (tx_type > 0):
                self.cursor += 2  # extraPayload

        return base_tx


@dataclass
class TxTime:
    '''Class representing transaction that has a time field.'''
    __slots__ = 'version', 'time', 'inputs', 'outputs', 'locktime'
    version: int
    time: int
    inputs: Sequence
    outputs: Sequence
    locktime: int


class DeserializerTxTime(Deserializer):
    def read_tx(self):
        return TxTime(
            self._read_le_int32(),   # version
            self._read_le_uint32(),  # time
            self._read_inputs(),     # inputs
            self._read_outputs(),    # outputs
            self._read_le_uint32(),  # locktime
        )


@dataclass
class TxTimeSegWit:
    '''Class representing a SegWit transaction with time.'''
    __slots__ = ('version', 'time', 'marker', 'flag', 'inputs', 'outputs',
                 'witness', 'locktime')
    version: int
    time: int
    marker: int
    flag: int
    inputs: Sequence
    outputs: Sequence
    witness: Sequence
    locktime: int


class DeserializerTxTimeSegWit(DeserializerTxTime):
    def _read_witness(self, fields):
        read_witness_field = self._read_witness_field
        return [read_witness_field() for _ in range(fields)]

    def _read_witness_field(self):
        read_varbytes = self._read_varbytes
        return [read_varbytes() for _ in range(self._read_varint())]

    def _read_tx_parts(self):
        '''Return a (deserialized TX, tx_hash, vsize) tuple.'''
        start = self.cursor
        marker = self.binary[self.cursor + 8]
        if marker:
            tx = super().read_tx()
            tx_hash = self.TX_HASH_FN(self.binary[start:self.cursor])
            return tx, tx_hash, self.binary_length

        version = self._read_le_int32()
        time = self._read_le_uint32()
        orig_ser = self.binary[start:self.cursor]

        marker = self._read_byte()
        flag = self._read_byte()

        start = self.cursor
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        orig_ser += self.binary[start:self.cursor]

        base_size = self.cursor - start
        witness = self._read_witness(len(inputs))

        start = self.cursor
        locktime = self._read_le_uint32()
        orig_ser += self.binary[start:self.cursor]
        vsize = (3 * base_size + self.binary_length) // 4

        return TxTimeSegWit(
            version, time, marker, flag, inputs, outputs, witness, locktime),\
            self.TX_HASH_FN(orig_ser), vsize

    def read_tx(self):
        return self._read_tx_parts()[0]

    def read_tx_and_hash(self):
        tx, tx_hash, vsize = self._read_tx_parts()
        return tx, tx_hash

    def read_tx_and_vsize(self):
        tx, tx_hash, vsize = self._read_tx_parts()
        return tx, vsize


class DeserializerTxTimeSegWitNavCoin(DeserializerTxTime):
    def _read_witness(self, fields):
        read_witness_field = self._read_witness_field
        return [read_witness_field() for _ in range(fields)]

    def _read_witness_field(self):
        read_varbytes = self._read_varbytes
        return [read_varbytes() for _ in range(self._read_varint())]

    def read_tx_no_segwit(self):
        version = self._read_le_int32()
        time = self._read_le_uint32()
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        locktime = self._read_le_uint32()
        strDZeel = ""
        if version >= 2:
            strDZeel = self._read_varbytes()
        return TxTime(
            version,
            time,
            inputs,
            outputs,
            locktime
        )

    def _read_tx_parts(self):
        '''Return a (deserialized TX, tx_hash, vsize) tuple.'''
        start = self.cursor
        marker = self.binary[self.cursor + 8]
        if marker:
            tx = self.read_tx_no_segwit()
            tx_hash = self.TX_HASH_FN(self.binary[start:self.cursor])
            return tx, tx_hash, self.binary_length

        version = self._read_le_int32()
        time = self._read_le_uint32()
        orig_ser = self.binary[start:self.cursor]

        marker = self._read_byte()
        flag = self._read_byte()

        start = self.cursor
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        orig_ser += self.binary[start:self.cursor]

        base_size = self.cursor - start
        witness = self._read_witness(len(inputs))

        start = self.cursor
        locktime = self._read_le_uint32()
        strDZeel = ""

        if version >= 2:
            strDZeel = self._read_varbytes()

        vsize = (3 * base_size + self.binary_length) // 4
        orig_ser += self.binary[start:self.cursor]

        return TxTimeSegWit(
            version, time, marker, flag, inputs, outputs, witness, locktime),\
            self.TX_HASH_FN(orig_ser), vsize

    def read_tx(self):
        return self._read_tx_parts()[0]

    def read_tx_and_hash(self):
        tx, tx_hash, vsize = self._read_tx_parts()
        return tx, tx_hash

    def read_tx_and_vsize(self):
        tx, tx_hash, vsize = self._read_tx_parts()
        return tx, vsize


@dataclass
class TxTrezarcoin:
    '''Class representing transaction that has a time and txcomment field.'''
    __slots__ = ('version', 'time', 'inputs', 'outputs', 'locktime',
                 'txcomment')
    version: int
    time: int
    inputs: Sequence
    outputs: Sequence
    locktime: int
    txcomment: bytes


class DeserializerTrezarcoin(Deserializer):

    def read_tx(self):
        version = self._read_le_int32()
        time = self._read_le_uint32()
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        locktime = self._read_le_uint32()
        if version >= 2:
            txcomment = self._read_varbytes()
        else:
            txcomment = b''
        return TxTrezarcoin(version, time, inputs, outputs, locktime,
                            txcomment)

    @staticmethod
    def blake2s_gen(data):
        keyOne = data[36:46]
        keyTwo = data[58:68]
        ntime = data[68:72]
        _nBits = data[72:76]
        _nonce = data[76:80]
        _full_merkle = data[36:68]
        _input112 = data + _full_merkle
        _key = keyTwo + ntime + _nBits + _nonce + keyOne
        # Prepare 112Byte Header
        blake2s_hash = blake2s(_input112, digest_size=32, key=_key)
        # TrezarFlips - Only for Genesis
        return ''.join(map(str.__add__, blake2s_hash.hexdigest()[-2::-2],
                           blake2s_hash.hexdigest()[-1::-2]))

    @staticmethod
    def blake2s(data):
        keyOne = data[36:46]
        keyTwo = data[58:68]
        ntime = data[68:72]
        _nBits = data[72:76]
        _nonce = data[76:80]
        _full_merkle = data[36:68]
        _input112 = data + _full_merkle
        _key = keyTwo + ntime + _nBits + _nonce + keyOne
        # Prepare 112Byte Header
        blake2s_hash = blake2s(_input112, digest_size=32, key=_key)
        # TrezarFlips
        return blake2s_hash.digest()


class DeserializerReddcoin(Deserializer):
    def read_tx(self):
        version = self._read_le_int32()
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        locktime = self._read_le_uint32()
        if version > 1:
            time = self._read_le_uint32()
        else:
            time = 0

        return TxTime(version, time, inputs, outputs, locktime)


class DeserializerVerge(Deserializer):
    def read_tx(self):
        version = self._read_le_int32()
        time = self._read_le_uint32()
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        locktime = self._read_le_uint32()

        return TxTime(version, time, inputs, outputs, locktime)


class DeserializerEmercoin(DeserializerTxTimeSegWit):
    VERSION_AUXPOW = (1 << 8)

    def is_merged_block(self):
        start = self.cursor
        self.cursor = 0
        version = self._read_le_uint32()
        self.cursor = start
        if version & self.VERSION_AUXPOW:
            return True
        return False

    def read_header(self, static_header_size):
        '''Return the AuxPow block header bytes'''
        start = self.cursor
        version = self._read_le_uint32()
        if version & self.VERSION_AUXPOW:
            # We are going to calculate the block size then read it as bytes
            self.cursor = start
            self.cursor += static_header_size  # Block normal header
            self.read_tx()  # AuxPow transaction
            self.cursor += 32  # Parent block hash
            merkle_size = self._read_varint()
            self.cursor += 32 * merkle_size  # Merkle branch
            self.cursor += 4  # Index
            merkle_size = self._read_varint()
            self.cursor += 32 * merkle_size  # Chain merkle branch
            self.cursor += 4  # Chain index
            self.cursor += 80  # Parent block header
            header_end = self.cursor
        else:
            header_end = static_header_size
        self.cursor = start
        return self._read_nbytes(header_end)


class DeserializerBitcoinAtom(DeserializerSegWit):
    FORK_BLOCK_HEIGHT = 505888

    def read_header(self, height, static_header_size):
        '''Return the block header bytes'''
        header_len = static_header_size
        if height >= self.FORK_BLOCK_HEIGHT:
            header_len += 4  # flags
        return self._read_nbytes(header_len)


class DeserializerGroestlcoin(DeserializerSegWit):
    TX_HASH_FN = staticmethod(sha256)


class TxInputTokenPay(TxInput):
    '''Class representing a TokenPay transaction input.'''

    OP_ANON_MARKER = 0xb9
    # 2byte marker (cpubkey + sigc + sigr)
    MIN_ANON_IN_SIZE = 2 + (33 + 32 + 32)

    def _is_anon_input(self):
        return (len(self.script) >= self.MIN_ANON_IN_SIZE and
                self.script[0] == OpCodes.OP_RETURN and
                self.script[1] == self.OP_ANON_MARKER)

    def is_generation(self):
        # Transactions comming in from stealth addresses are seen by
        # the blockchain as newly minted coins. The reverse, where coins
        # are sent TO a stealth address, are seen by the blockchain as
        # a coin burn.
        if self._is_anon_input():
            return True
        return super(TxInputTokenPay, self).is_generation()


@dataclass
class TxInputTokenPayStealth:
    '''Class representing a TokenPay stealth transaction input.'''
    __slots__ = 'keyimage', 'ringsize', 'script', 'sequence'
    keyimage: bytes
    ringsize: bytes
    script: bytes
    sequence: int

    def __str__(self):
        script = self.script.hex()
        keyimage = bytes(self.keyimage).hex()
        return (f"Input({keyimage}, {self.ringsize[1]:d}, script={script}, "
                f"sequence={self.sequence:d})")

    def is_generation(self):
        return True

    def serialize(self):
        return b''.join((
            self.keyimage,
            self.ringsize,
            pack_varbytes(self.script),
            pack_le_uint32(self.sequence),
        ))


class DeserializerTokenPay(DeserializerTxTime):

    def _read_input(self):
        txin = TxInputTokenPay(
            self._read_nbytes(32),   # prev_hash
            self._read_le_uint32(),  # prev_idx
            self._read_varbytes(),   # script
            self._read_le_uint32(),  # sequence
        )
        if txin._is_anon_input():
            # Not sure if this is actually needed, and seems
            # extra work for no immediate benefit, but it at
            # least correctly represents a stealth input
            raw = txin.serialize()
            deserializer = Deserializer(raw)
            txin = TxInputTokenPayStealth(
                deserializer._read_nbytes(33),  # keyimage
                deserializer._read_nbytes(3),   # ringsize
                deserializer._read_varbytes(),  # script
                deserializer._read_le_uint32()  # sequence
            )
        return txin


# Decred
@dataclass
class TxInputDcr:
    '''Class representing a Decred transaction input.'''
    __slots__ = 'prev_hash', 'prev_idx', 'tree', 'sequence'
    prev_hash: bytes
    prev_idx: int
    tree: int
    sequence: int

    def __str__(self):
        prev_hash = hash_to_hex_str(self.prev_hash)
        return (f"Input({prev_hash}, {self.prev_idx:d}, tree={self.tree}, "
                f"sequence={self.sequence:d})")

    def is_generation(self):
        '''Test if an input is generation/coinbase like'''
        return self.prev_idx == MINUS_1 and self.prev_hash == ZERO


@dataclass
class TxOutputDcr:
    '''Class representing a Decred transaction output.'''
    __slots__ = 'value', 'version', 'pk_script'
    value: int
    version: int
    pk_script: bytes


@dataclass
class TxDcr:
    '''Class representing a Decred  transaction.'''
    __slots__ = 'version', 'inputs', 'outputs', 'locktime', 'expiry', 'witness'
    version: int
    inputs: Sequence
    outputs: Sequence
    locktime: int
    expiry: int
    witness: Sequence


class DeserializerDecred(Deserializer):
    @staticmethod
    def blake256(data):
        from blake256.blake256 import blake_hash
        return blake_hash(data)

    @staticmethod
    def blake256d(data):
        from blake256.blake256 import blake_hash
        return blake_hash(blake_hash(data))

    def read_tx(self):
        return self._read_tx_parts(produce_hash=False)[0]

    def read_tx_and_hash(self):
        tx, tx_hash, _vsize = self._read_tx_parts()
        return tx, tx_hash

    def read_tx_and_vsize(self):
        tx, _tx_hash, vsize = self._read_tx_parts(produce_hash=False)
        return tx, vsize

    def read_tx_block(self):
        '''Returns a list of (deserialized_tx, tx_hash) pairs.'''
        read = self.read_tx_and_hash
        txs = [read() for _ in range(self._read_varint())]
        stxs = [read() for _ in range(self._read_varint())]
        return txs + stxs

    def read_tx_tree(self):
        '''Returns a list of deserialized_tx without tx hashes.'''
        read_tx = self.read_tx
        return [read_tx() for _ in range(self._read_varint())]

    def _read_input(self):
        return TxInputDcr(
            self._read_nbytes(32),   # prev_hash
            self._read_le_uint32(),  # prev_idx
            self._read_byte(),       # tree
            self._read_le_uint32(),  # sequence
        )

    def _read_output(self):
        return TxOutputDcr(
            self._read_le_int64(),  # value
            self._read_le_uint16(),  # version
            self._read_varbytes(),  # pk_script
        )

    def _read_witness(self, fields):
        read_witness_field = self._read_witness_field
        assert fields == self._read_varint()
        return [read_witness_field() for _ in range(fields)]

    def _read_witness_field(self):
        value_in = self._read_le_int64()
        block_height = self._read_le_uint32()
        block_index = self._read_le_uint32()
        script = self._read_varbytes()
        return value_in, block_height, block_index, script

    def _read_tx_parts(self, produce_hash=True):
        start = self.cursor
        version = self._read_le_int32()
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        locktime = self._read_le_uint32()
        expiry = self._read_le_uint32()
        end_prefix = self.cursor
        witness = self._read_witness(len(inputs))

        if produce_hash:
            # TxSerializeNoWitness << 16 == 0x10000
            no_witness_header = pack_le_uint32(0x10000 | (version & 0xffff))
            prefix_tx = no_witness_header + self.binary[start+4:end_prefix]
            tx_hash = self.blake256(prefix_tx)
        else:
            tx_hash = None

        return TxDcr(
            version,
            inputs,
            outputs,
            locktime,
            expiry,
            witness
        ), tx_hash, self.cursor - start


class DeserializerSmartCash(Deserializer):

    @staticmethod
    def keccak(data):
        from Cryptodome.Hash import keccak
        keccak_hash = keccak.new(data=data, digest_bits=256)
        return keccak_hash.digest()

    def read_tx_and_hash(self):
        start = self.cursor
        return self.read_tx(), sha256(self.binary[start:self.cursor])


@dataclass
class TxBitcoinDiamond:
    '''Class representing a transaction.'''
    __slots__ = 'version', 'preblockhash', 'inputs', 'outputs', 'locktime'
    version: int
    preblockhash: str
    inputs: Sequence
    outputs: Sequence
    locktime: int


class DeserializerBitcoinDiamond(Deserializer):
    bitcoin_diamond_tx_version = 12

    def read_tx(self):
        # Return a Deserialized TX.
        version = self._get_version()
        if version != self.bitcoin_diamond_tx_version:
            return Tx(
                self._read_le_int32(),  # version
                self._read_inputs(),    # inputs
                self._read_outputs(),   # outputs
                self._read_le_uint32()  # locktime
            )
        else:
            return TxBitcoinDiamond(
                self._read_le_int32(),  # version
                hash_to_hex_str(self._read_nbytes(32)),  # blockhash
                self._read_inputs(),  # inputs
                self._read_outputs(),  # outputs
                self._read_le_uint32()  # locktime
            )

    def _get_version(self):
        result, = unpack_le_int32_from(self.binary, self.cursor)
        return result


@dataclass
class TxBitcoinDiamondSegWit:
    '''Class representing a SegWit transaction.'''
    __slots__ = ('version', 'preblockhash', 'marker', 'flag', 'inputs',
                 'outputs', 'witness', 'locktime')
    version: int
    preblockhash: str
    marker: int
    flag: int
    inputs: Sequence
    outputs: Sequence
    witness: Sequence
    locktime: int


class DeserializerBitcoinDiamondSegWit(DeserializerBitcoinDiamond,
                                       DeserializerSegWit):
    def _read_tx_parts(self):
        '''Return a (deserialized TX, tx_hash, vsize) tuple.'''
        start = self.cursor
        tx_version = self._get_version()
        if tx_version == self.bitcoin_diamond_tx_version:
            marker = self.binary[self.cursor + 4 + 32]
        else:
            marker = self.binary[self.cursor + 4]

        if marker:
            tx = super().read_tx()
            tx_hash = self.TX_HASH_FN(self.binary[start:self.cursor])
            return tx, tx_hash, self.binary_length

        # Ugh, this is nasty.
        version = self._read_le_int32()
        present_block_hash = None
        if version == self.bitcoin_diamond_tx_version:
            present_block_hash = hash_to_hex_str(self._read_nbytes(32))
        orig_ser = self.binary[start:self.cursor]

        marker = self._read_byte()
        flag = self._read_byte()

        start = self.cursor
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        orig_ser += self.binary[start:self.cursor]

        base_size = self.cursor - start
        witness = self._read_witness(len(inputs))

        start = self.cursor
        locktime = self._read_le_uint32()
        orig_ser += self.binary[start:self.cursor]
        vsize = (3 * base_size + self.binary_length) // 4

        if present_block_hash is not None:
            return TxBitcoinDiamondSegWit(
                version, present_block_hash, marker, flag, inputs, outputs,
                witness, locktime), self.TX_HASH_FN(orig_ser), vsize
        else:
            return TxSegWit(
                version, marker, flag, inputs, outputs, witness,
                locktime), self.TX_HASH_FN(orig_ser), vsize

    def read_tx(self):
        '''Return a (Deserialized TX, TX_HASH) pair.

        The hash needs to be reversed for human display; for efficiency
        we process it in the natural serialized order.
        '''
        return self._read_tx_parts()[0]


class DeserializerElectra(Deserializer):
    ELECTRA_TX_VERSION = 7

    def _get_version(self):
        result, = unpack_le_int32_from(self.binary, self.cursor)
        return result

    def read_tx(self):
        version = self._get_version()
        if version != self.ELECTRA_TX_VERSION:
            return TxTime(
                self._read_le_int32(),   # version
                self._read_le_uint32(),  # time
                self._read_inputs(),     # inputs
                self._read_outputs(),    # outputs
                self._read_le_uint32(),  # locktime
            )
        else:
            return Tx(
                self._read_le_int32(),  # version
                self._read_inputs(),    # inputs
                self._read_outputs(),   # outputs
                self._read_le_uint32()  # locktime
            )


class DeserializerECCoin(Deserializer):
    def read_tx(self):
        tx_version = self._read_le_int32()
        tx = TxTime(
            tx_version,
            self._read_le_uint32(),
            self._read_inputs(),
            self._read_outputs(),
            self._read_le_uint32(),
        )

        if tx_version > 1:
            self.cursor += 32

        return tx


class DeserializerZcoin(Deserializer):
    def _read_input(self):
        tx_input = TxInput(
            self._read_nbytes(32),   # prev_hash
            self._read_le_uint32(),  # prev_idx
            self._read_varbytes(),   # script
            self._read_le_uint32()   # sequence
        )

        if tx_input.prev_idx == MINUS_1 and tx_input.prev_hash == ZERO:
            return tx_input

        if tx_input.script[0] == 0xc4:  # This is a Sigma spend - mimic a generation tx
            return TxInput(
                ZERO,
                MINUS_1,
                tx_input.script,
                tx_input.sequence
            )

        return tx_input


class DeserializerXaya(DeserializerSegWit, DeserializerAuxPow):
    """Deserializer class for the Xaya network

    The main difference to other networks is the changed format of the
    block header with "triple purpose mining", see
    https://github.com/xaya/xaya/blob/master/doc/xaya/mining.md.

    This builds upon classic auxpow, but has a modified serialisation format
    that we have to implement here."""

    MM_FLAG = 0x80

    def read_header(self, static_header_size):
        """Reads in the full block header (including PoW data)"""

        # We first calculate the dynamic size of the block header, and then
        # read in all the data in the final step.
        start = self.cursor

        self.cursor += static_header_size  # Normal block header

        algo = self._read_byte()
        self._read_le_uint32()  # nBits

        if algo & self.MM_FLAG:
            self.read_auxpow()
        else:
            self.cursor += static_header_size  # Fake header

        end = self.cursor
        self.cursor = start
        return self._read_nbytes(end - start)


class DeserializerSimplicity(Deserializer):
    SIMPLICITY_TX_VERSION = 3

    def _get_version(self):
        result, = unpack_le_int32_from(self.binary, self.cursor)
        return result

    def read_tx(self):
        version = self._get_version()
        if version < self.SIMPLICITY_TX_VERSION:
            return TxTime(
                self._read_le_int32(),   # version
                self._read_le_uint32(),  # time
                self._read_inputs(),     # inputs
                self._read_outputs(),    # outputs
                self._read_le_uint32(),  # locktime
            )
        else:
            return Tx(
                self._read_le_int32(),  # version
                self._read_inputs(),    # inputs
                self._read_outputs(),   # outputs
                self._read_le_uint32()  # locktime
            )


class DeserializerPrimecoin(Deserializer):
    def read_header(self, static_header_size):
        '''Return the block header bytes'''
        start = self.cursor
        # Decode the block header size including multiplier then read it as bytes
        self.cursor += static_header_size
        multiplier_size = self._read_varint()
        self.cursor += multiplier_size
        header_end = self.cursor
        self.cursor = start
        return self._read_nbytes(header_end - start)
