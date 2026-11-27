// Copyright (c) 2023 Institute of Software, Chinese Academy of Sciences
// Ripple is licensed under Mulan PSL v2.
// You can use this software according to the terms and conditions of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
//          http://license.coscl.org.cn/MulanPSL2
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

package ripple.common.tcp.decoder;

import io.netty.buffer.ByteBuf;
import ripple.common.entity.Constants;
import ripple.common.helper.TypeHelper;
import ripple.common.tcp.Decoder;
import ripple.common.tcp.Message;
import ripple.common.tcp.MessageType;
import ripple.common.tcp.PayloadCodec;
import ripple.common.tcp.message.SyncRequest;

import java.util.Date;

/**
 * @author Zhen Tang
 */
public class SyncRequestDecoder implements Decoder {
    @Override
    public Message decode(ByteBuf byteBuf, MessageType messageType) {
        return decodePacked(byteBuf, messageType, false);
    }

    @Override
    public Message decodePacked(ByteBuf byteBuf, MessageType messageType, boolean compressed) {
        SyncRequest syncRequest = new SyncRequest();
        syncRequest.setUuid(TypeHelper.readUuid(byteBuf));
        syncRequest.setMessageUuid(TypeHelper.readUuid(byteBuf));
        syncRequest.setOperationType(TypeHelper.isCompactWire()
                ? operationType(byteBuf.readUnsignedByte()) : TypeHelper.readString(byteBuf));
        syncRequest.setApplicationName(TypeHelper.readString(byteBuf));
        syncRequest.setKey(TypeHelper.readString(byteBuf));
        if (compressed && !Constants.MESSAGE_TYPE_UPDATE.equals(syncRequest.getOperationType())) {
            throw new IllegalArgumentException("Only ordinary SYNC updates can be compressed");
        }
        if (syncRequest.getOperationType().equals(Constants.MESSAGE_TYPE_UPDATE)) {
            syncRequest.setValue(compressed ? PayloadCodec.readCompressed(byteBuf) : TypeHelper.readString(byteBuf));
        } else if (syncRequest.getOperationType().equals(Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE)) {
            syncRequest.setBaseMessageUuid(TypeHelper.readUuid(byteBuf));
            syncRequest.setAtomicOperation(TypeHelper.readString(byteBuf));
            syncRequest.setValue(TypeHelper.readString(byteBuf));
        }
        syncRequest.setLastUpdate(new Date(byteBuf.readLong()));
        syncRequest.setLastUpdateServerId(byteBuf.readInt());
        syncRequest.setFromId(byteBuf.readInt());
        return syncRequest;
    }

    private static String operationType(int operationCode) {
        switch (operationCode) {
            case 1:
                return Constants.MESSAGE_TYPE_UPDATE;
            case 2:
                return Constants.MESSAGE_TYPE_DELETE;
            case 3:
                return Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE;
            default:
                throw new IllegalArgumentException("无效的同步操作编码: " + operationCode);
        }
    }
}
